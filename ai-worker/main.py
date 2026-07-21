"""
AI Worker — Pipeline Entry Point

Usage:
    python main.py --job-id <uuid> --storage-path <absolute-path>

Communicates with Node.js via newline-delimited JSON on stdout:
    {"status": "processing", "step": "<step_label>"}
    {"status": "done"}
    {"status": "error", "message": "<description>"}

Exit codes:
    0 — pipeline completed successfully
    1 — pipeline failed (error already emitted to stdout)
"""

import argparse
import gc
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import config
from config import GEMINI_API_KEY, LLM_ENABLED
from constants.pipeline_state import PipelineState, STEP_LABELS
from utils.logger import get_logger

logger = get_logger("main")


def emit(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


def emit_step(state: PipelineState) -> None:
    emit({"status": "processing", "step": STEP_LABELS[state]})


def run(job_id: str, storage_path: Path) -> None:
    start_time = time.time()

    pdf_path = storage_path / "uploads" / f"{job_id}.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # ── Stage 1: Page Classification ─────────────────────────────────────────
    emit_step(PipelineState.PAGE_CLASSIFICATION)
    from modules.page_classifier import classify_pages
    pairs = classify_pages(str(pdf_path))
    logger.info("Found %d assembly pair(s)", len(pairs))

    # ── Open PDF once for all rendering ──────────────────────────────────────
    import fitz  # PyMuPDF
    import cv2
    doc = fitz.open(str(pdf_path))
    mat = fitz.Matrix(config.PDF_RENDER_DPI / 72, config.PDF_RENDER_DPI / 72)

    from modules.image_preprocessor import preprocess
    from modules.circle_detector    import detect_circles, detect_colored_circles, merge_circle_lists
    from modules.callout_reader     import read_callouts
    from modules.bom_extractor      import extract_bom
    from modules.mapping_engine     import map_hotspots_to_bom

    total_pdf_pages = len(doc)
    assemblies: list[dict] = []

    for assembly_index, pair in enumerate(pairs):
        logger.info(
            "Processing assembly %d: diagram=page%d, bom=page%d",
            assembly_index, pair["diagram_page_index"], pair["bom_page_index"],
        )
        artifacts = config.get_artifact_paths(job_id, assembly_index)

        # ── Stage 2: PDF Rendering ────────────────────────────────────────────
        emit_step(PipelineState.PDF_RENDERING)
        diagram_page = doc[pair["diagram_page_index"]]
        pix = diagram_page.get_pixmap(matrix=mat, alpha=False)
        pix.save(str(artifacts["diagram"]))
        image_width, image_height = pix.width, pix.height
        logger.info(
            "Rendered assembly %d diagram at %d DPI - %dx%dpx -> %s",
            assembly_index, config.PDF_RENDER_DPI, image_width, image_height, artifacts["diagram"],
        )

        # ── Stage 2b: Crop to drawing area (exclude title block / footer) ─────
        diagram_image = cv2.imread(str(artifacts["diagram"]))
        scale = 72 / config.PDF_RENDER_DPI
        crop_y0, crop_y1 = _detect_drawing_crop(diagram_image)
        if crop_y0 > 0 or crop_y1 < diagram_image.shape[0]:
            diagram_image = diagram_image[crop_y0:crop_y1, :]
            cv2.imwrite(str(artifacts["diagram"]), diagram_image)
            image_height = diagram_image.shape[0]
            logger.info(
                "Assembly %d: cropped diagram to drawing area "
                "(removed %dpx header + %dpx footer). New: %dx%dpx",
                assembly_index, crop_y0,
                pix.height - crop_y1, image_width, image_height,
            )
        del pix

        # ── Stage 3: Image Preprocessing ─────────────────────────────────────
        emit_step(PipelineState.IMAGE_PREPROCESSING)
        preprocessed = preprocess(diagram_image, debug=config.DEBUG)
        if config.DEBUG:
            cv2.imwrite(str(artifacts["preprocessed"]), preprocessed)

        # ── Stage 4: Circle Detection ─────────────────────────────────────────
        emit_step(PipelineState.CIRCLE_DETECTION)

        # Pass 1: contour-based detection on binary preprocessed image.
        # Finds dark-outlined circles (white paper + dark ring → white ring in binary).
        circles = detect_circles(preprocessed)
        _n_standard = len(circles)
        logger.info(
            "Assembly %d: binary pass detected %d circle(s)",
            assembly_index, _n_standard,
        )
        del preprocessed
        gc.collect()

        # Pass 2: HSV connected-component detection on the original color image.
        # Finds filled-color circles (yellow, amber, cream) that THRESH_BINARY_INV
        # makes invisible. Shape filters (aspect ratio + compactness) reject large
        # non-circular colored parts (axle bodies, straps, brackets).
        colored_circles = detect_colored_circles(diagram_image)
        _n_colored = len(colored_circles)
        if colored_circles:
            logger.info(
                "Assembly %d: color pass detected %d circle(s) — merging",
                assembly_index, _n_colored,
            )
            circles = merge_circle_lists(circles, colored_circles)
            logger.info(
                "Assembly %d: %d circle(s) after merge + dedup",
                assembly_index, len(circles),
            )
        logger.info(
            "[CIRCLE] assembly=%d standard=%d colored=%d merged=%d",
            assembly_index, _n_standard, _n_colored, len(circles),
        )

        if config.DEBUG:
            _save_circle_debug(diagram_image, circles, artifacts)

        # ── Stage 5: Callout Reading ──────────────────────────────────────────
        emit_step(PipelineState.CALLOUT_READING)
        callouts = read_callouts(diagram_image, circles, diagram_page, scale, crop_y0=crop_y0)
        _n_raw_ocr = len(callouts)

        # Drop OCR callouts that land inside a colored circle — OCR misclassifies
        # digits on yellow-fill circles (e.g. reads "2" as "7"). Strategy E
        # (Gemini) handles colored circles correctly when LLM is enabled; without
        # LLM they surface as unpositioned, which is honest and safe.
        _n_dropped_colored = 0
        colored_ocr_fallbacks: dict[str, dict] = {}
        if colored_circles:
            import math as _math
            def _in_colored_circle(callout):
                for cc in colored_circles:
                    dist = _math.sqrt((callout["x"] - cc["x"]) ** 2 + (callout["y"] - cc["y"]) ** 2)
                    if dist <= cc["radius"]:
                        return True
                return False
            kept = []
            for c in callouts:
                if _in_colored_circle(c):
                    ref = str(c["number"]).strip().lstrip("0") or "0"
                    colored_ocr_fallbacks[ref] = c
                else:
                    kept.append(c)
            callouts = kept
            _n_dropped_colored = len(colored_ocr_fallbacks)
            if _n_dropped_colored:
                logger.info(
                    "Assembly %d: dropped %d OCR callout(s) inside colored circles — left for Strategy E",
                    assembly_index, _n_dropped_colored,
                )

        logger.info("Assembly %d: read %d callout numbers", assembly_index, len(callouts))
        logger.info(
            "[CALLOUT] assembly=%d input_circles=%d raw_ocr=%d dropped_colored=%d final=%d",
            assembly_index, len(circles), _n_raw_ocr, _n_dropped_colored, len(callouts),
        )
        if config.DEBUG:
            artifacts["ocr_results"].write_text(
                json.dumps(callouts, indent=2), encoding="utf-8"
            )

        # ── Stage 6: BOM Extraction ───────────────────────────────────────────
        emit_step(PipelineState.BOM_EXTRACTION)
        bom_rows = extract_bom(str(pdf_path), pair["bom_page_index"])
        total_parts = len(bom_rows)  # count before any categorization
        logger.info("Assembly %d: extracted %d BOM rows", assembly_index, total_parts)
        if config.DEBUG:
            artifacts["bom_raw"].write_text(
                json.dumps(bom_rows, indent=2), encoding="utf-8"
            )

        # ── Stage D: Enhanced unresolved-circle recovery ─────────────────────
        from modules.strategy_d_recovery import recover_unresolved_circles
        strategy_d_recovered = recover_unresolved_circles(
            diagram_image=diagram_image,
            circles=circles,
            existing_callouts=callouts,
            bom_rows=bom_rows,
        )
        if strategy_d_recovered:
            logger.info(
                "Assembly %d: Strategy D recovered %d ref(s): %s",
                assembly_index, len(strategy_d_recovered),
                [r["number"] for r in strategy_d_recovered],
            )
            callouts = callouts + strategy_d_recovered
        logger.info(
            "[STRATEGY_D] assembly=%d attempted=%d recovered=%d total_after=%d",
            assembly_index, len(circles), len(strategy_d_recovered), len(callouts),
        )

        # ── Stage E: Gemini Vision targeted recovery ──────────────────────────
        _strategy_e_recovered_refs: set[str] = set()
        if LLM_ENABLED and GEMINI_API_KEY:
            _e_before = len(callouts)
            from modules.strategy_e_recovery import recover_with_gemini
            strategy_e_recovered = recover_with_gemini(
                diagram_image=diagram_image,
                circles=circles,
                existing_callouts=callouts,
                bom_rows=bom_rows,
            )
            if strategy_e_recovered:
                _strategy_e_recovered_refs = {
                    str(r["number"]).strip().lstrip("0") or "0"
                    for r in strategy_e_recovered
                }
                logger.info(
                    "Assembly %d: Strategy E recovered %d ref(s): %s",
                    assembly_index, len(strategy_e_recovered),
                    [r["number"] for r in strategy_e_recovered],
                )
                callouts = callouts + strategy_e_recovered
            logger.info(
                "[STRATEGY_E] assembly=%d attempted=True recovered=%d total_after=%d",
                assembly_index, len(strategy_e_recovered), len(callouts),
            )
        else:
            logger.info(
                "[STRATEGY_E] assembly=%d attempted=False recovered=0 reason=LLM_DISABLED",
                assembly_index,
            )

        # Restore colored OCR fallbacks for refs not resolved by any strategy.
        # Checks against all current callouts (covers Strategy D and E) to avoid
        # adding duplicate hotspots for refs already positioned by another source.
        if colored_ocr_fallbacks:
            _norm = lambda r: str(r).strip().lstrip("0") or "0"
            _bom_refs = {_norm(r["ref_no"]) for r in bom_rows}
            _already_resolved = {_norm(c["number"]) for c in callouts}
            _restored = [
                fb for ref, fb in colored_ocr_fallbacks.items()
                if ref not in _already_resolved and ref in _bom_refs
            ]
            if _restored:
                callouts = callouts + _restored
                logger.info(
                    "Assembly %d: restored %d colored OCR fallback(s) Strategy E did not resolve: %s",
                    assembly_index, len(_restored), [r["number"] for r in _restored],
                )

        logger.info("[HOTSPOTS] assembly=%d final=%d", assembly_index, len(callouts))

        # diagram_image is no longer needed — release before mapping to free RAM
        del diagram_image
        gc.collect()

        # ── Stage 7: Mapping ──────────────────────────────────────────────────
        emit_step(PipelineState.MAPPING)
        mapping_result = map_hotspots_to_bom(callouts, bom_rows)
        logger.info(
            "Assembly %d: %d mapped, %d unmapped, %d unpositioned, %d not-shown",
            assembly_index,
            len(mapping_result["mappings"]),
            len(mapping_result["unmapped_hotspots"]),
            len(mapping_result["unpositioned_bom_rows"]),
            len(mapping_result["not_shown_bom_rows"]),
        )
        if config.DEBUG:
            artifacts["mappings_debug"].write_text(
                json.dumps(mapping_result, indent=2), encoding="utf-8"
            )

        # ── Stage 8 (optional): LLM Validation ───────────────────────────────
        _has_fuzzy = any(m["confidence"] < 1.0 for m in mapping_result["mappings"])
        if config.LLM_ENABLED and (mapping_result["unmapped_hotspots"] or _has_fuzzy):
            # Exclude unmapped hotspots whose ref doesn't exist in the BOM.
            # These are OCR false positives that Gemini cannot resolve.
            _norm_r = lambda r: str(r).strip().lstrip("0") or "0"
            _bom_ref_set = {_norm_r(r["ref_no"]) for r in bom_rows}
            _all_unmapped     = mapping_result["unmapped_hotspots"]
            _valid_unmapped   = [h for h in _all_unmapped if _norm_r(h["number"]) in _bom_ref_set]
            _invalid_unmapped = [h for h in _all_unmapped if _norm_r(h["number"]) not in _bom_ref_set]
            if _invalid_unmapped:
                logger.info(
                    "Assembly %d: excluding %d unmapped ref(s) not in BOM from llm_resolver: %s",
                    assembly_index, len(_invalid_unmapped),
                    [h["number"] for h in _invalid_unmapped],
                )
            if _valid_unmapped or _has_fuzzy:
                emit_step(PipelineState.LLM_VALIDATION)
                from modules.llm_resolver import resolve_with_llm
                _resolver_input = {**mapping_result, "unmapped_hotspots": _valid_unmapped}
                mapping_result = resolve_with_llm(
                    mapping_result=_resolver_input,
                    bom_rows=bom_rows,
                )
                # Restore invalid refs so they remain visible in the final result
                mapping_result = {
                    **mapping_result,
                    "unmapped_hotspots": mapping_result["unmapped_hotspots"] + _invalid_unmapped,
                }
                logger.info(
                    "Assembly %d: LLM validation — %d decision(s)",
                    assembly_index, len(mapping_result["llm_validations"]),
                )
            else:
                mapping_result = {**mapping_result, "llm_validations": [], "unmapped_hotspots": _all_unmapped}
        else:
            mapping_result["llm_validations"] = []

        assemblies.append({
            "assembly_index":      assembly_index,
            "page_map":            pair,
            "diagram_image_path":  f"outputs/{job_id}/assembly_{assembly_index}/diagram.png",
            "image_width":         image_width,
            "image_height":        image_height,
            "total_parts":         total_parts,
            "hotspots":            callouts,
            "bom":                 bom_rows,
            "mappings":            mapping_result["mappings"],
            "unmapped_hotspots":   mapping_result["unmapped_hotspots"],
            "unpositioned_bom_rows": mapping_result["unpositioned_bom_rows"],
            "not_shown_bom_rows":  mapping_result["not_shown_bom_rows"],
            "llm_validations":     mapping_result["llm_validations"],
        })

    doc.close()

    # ── Stage 9: Result Generation ────────────────────────────────────────────
    emit_step(PipelineState.RESULT_GENERATION)
    from modules.result_writer import write_result
    duration_ms = int((time.time() - start_time) * 1000)
    job_dir = config.get_job_dir(job_id)
    write_result(
        job_output_dir=job_dir,
        processing_duration_ms=duration_ms,
        total_pdf_pages=total_pdf_pages,
        assemblies=assemblies,
    )

    logger.info("Pipeline complete in %dms -> %s/result.json", duration_ms, job_dir)
    emit({"status": "done"})


def _detect_drawing_crop(diagram_image) -> tuple[int, int]:
    """
    Find the drawing frame borders using horizontal projection profile.

    Engineering PDFs (Bobcat style) have a visible rectangular border around
    the drawing area. Above it: plain-text title block. Below it: footer.

    Strategy:
      1. Binarize (Otsu threshold on grayscale).
      2. For each row, count dark pixels. A border line has a long unbroken
         dark span — quantified as: ≥30% of image width pixels are dark AND
         the longest unbroken dark run in that row is ≥25% of width.
      3. Collect all qualifying row y-values.
         top border  = topmost qualifying row below the top 5% of image
         bottom border = bottommost qualifying row above the bottom 5%
      4. Sanity check: cropped area must be ≥25% of original height.

    Falls back to (0, image_height) — no crop — if detection fails.
    """
    import cv2
    import numpy as np
    h, w = diagram_image.shape[:2]

    try:
        gray = cv2.cvtColor(diagram_image, cv2.COLOR_BGR2GRAY)
        # Otsu binarization: dark pixels (border lines) become 0, paper becomes 255
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        dark = (binary == 0).astype(np.uint8)  # 1 where dark

        min_dark_pixels  = int(w * 0.30)   # row must have ≥30% dark pixels
        min_run_length   = int(w * 0.25)   # longest dark run must be ≥25% of width

        border_rows = []
        for y in range(h):
            row = dark[y]
            if row.sum() < min_dark_pixels:
                continue
            # Find the longest contiguous run of dark pixels
            max_run = 0
            run = 0
            for px in row:
                if px:
                    run += 1
                    if run > max_run:
                        max_run = run
                else:
                    run = 0
            if max_run >= min_run_length:
                border_rows.append(y)

        logger.debug("  crop detect: %d border row(s) found", len(border_rows))

        if len(border_rows) < 2:
            logger.debug("  crop detect: <2 border rows — no crop applied")
            return 0, h

        # Top of drawing frame: topmost border row below top 5%
        top_cands = [y for y in border_rows if y > h * 0.05]
        # Bottom of drawing frame: bottommost border row above bottom 5%
        bot_cands = [y for y in border_rows if y < h * 0.95]

        if not top_cands or not bot_cands:
            logger.debug("  crop detect: no usable top/bottom candidates — no crop applied")
            return 0, h

        crop_y0 = max(0, min(top_cands) - 2)
        crop_y1 = min(h, max(bot_cands) + 2)

        if crop_y0 >= crop_y1 or (crop_y1 - crop_y0) < h * 0.25:
            logger.debug("  crop detect: implausible bounds (%d..%d) — no crop applied",
                         crop_y0, crop_y1)
            return 0, h

        logger.info(
            "  crop detect: drawing frame y=%d (%.0f%%) .. y=%d (%.0f%%)",
            crop_y0, 100 * crop_y0 / h,
            crop_y1, 100 * crop_y1 / h,
        )
        return crop_y0, crop_y1

    except Exception as exc:
        logger.warning("  crop detect: failed (%s) — no crop applied", exc)
        return 0, h


def _save_circle_debug(diagram_image, circles, artifacts):
    import cv2
    debug_img = diagram_image.copy()
    for c in circles:
        cv2.circle(debug_img, (c["x"], c["y"]), c["radius"], (0, 255, 0), 2)
        cv2.circle(debug_img, (c["x"], c["y"]), 2, (0, 0, 255), 3)
    cv2.imwrite(str(artifacts["circles"]), debug_img)
    logger.debug("Saved circle debug image → %s", artifacts["circles"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Engineering PDF Analyzer — AI Worker")
    parser.add_argument("--job-id",       required=True, help="Unique job identifier (UUID)")
    parser.add_argument("--storage-path", required=True, help="Absolute path to shared storage root")
    args = parser.parse_args()

    try:
        run(job_id=args.job_id, storage_path=Path(args.storage_path))
    except NotImplementedError as exc:
        logger.error("Not implemented: %s", exc)
        emit({"status": "error", "message": f"Module not yet implemented: {exc}"})
        sys.exit(1)
    except Exception as exc:
        logger.exception("Unhandled pipeline error")
        emit({"status": "error", "message": str(exc)})
        sys.exit(1)


if __name__ == "__main__":
    main()
