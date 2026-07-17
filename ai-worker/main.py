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
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import config
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
    from modules.circle_detector    import detect_circles
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

        # ── Stage 3: Image Preprocessing ─────────────────────────────────────
        emit_step(PipelineState.IMAGE_PREPROCESSING)
        diagram_image = cv2.imread(str(artifacts["diagram"]))
        preprocessed = preprocess(diagram_image, debug=config.DEBUG)
        if config.DEBUG:
            cv2.imwrite(str(artifacts["preprocessed"]), preprocessed)

        # ── Stage 4: Circle Detection ─────────────────────────────────────────
        emit_step(PipelineState.CIRCLE_DETECTION)
        circles = detect_circles(preprocessed)
        logger.info("Assembly %d: detected %d candidate circles", assembly_index, len(circles))
        if config.DEBUG:
            _save_circle_debug(diagram_image, circles, artifacts)

        # ── Stage 5: Callout Reading ──────────────────────────────────────────
        emit_step(PipelineState.CALLOUT_READING)
        scale = 72 / config.PDF_RENDER_DPI
        callouts = read_callouts(diagram_image, circles, diagram_page, scale)
        logger.info("Assembly %d: read %d callout numbers", assembly_index, len(callouts))
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
            emit_step(PipelineState.LLM_VALIDATION)
            from modules.llm_resolver import resolve_with_llm
            mapping_result = resolve_with_llm(
                mapping_result=mapping_result,
                bom_rows=bom_rows,
            )
            logger.info(
                "Assembly %d: LLM validation — %d decision(s)",
                assembly_index, len(mapping_result["llm_validations"]),
            )
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
