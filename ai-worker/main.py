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
    artifacts = config.get_artifact_paths(job_id)

    pdf_path = storage_path / "uploads" / f"{job_id}.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # ── Stage 1: Page Classification ─────────────────────────────────────────
    emit_step(PipelineState.PAGE_CLASSIFICATION)
    from modules.page_classifier import classify_pages
    page_map = classify_pages(str(pdf_path))
    logger.info(f"Page map: diagram={page_map['diagram_page_index']}, "
                f"bom={page_map['bom_page_index']}, "
                f"confidence={page_map['classification_confidence']}")

    # ── Stage 2: PDF Rendering ────────────────────────────────────────────────
    emit_step(PipelineState.PDF_RENDERING)
    import fitz  # PyMuPDF
    doc = fitz.open(str(pdf_path))
    mat = fitz.Matrix(config.PDF_RENDER_DPI / 72, config.PDF_RENDER_DPI / 72)

    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(str(artifacts["pages_dir"] / f"page_{i}.png"))

    diagram_page = doc[page_map["diagram_page_index"]]
    pix = diagram_page.get_pixmap(matrix=mat, alpha=False)
    pix.save(str(artifacts["diagram"]))
    image_width, image_height = pix.width, pix.height
    logger.info(f"Rendered diagram page at {config.PDF_RENDER_DPI} DPI - "
                f"{image_width}x{image_height}px -> {artifacts['diagram']}")

    # ── Stage 3: Image Preprocessing ─────────────────────────────────────────
    emit_step(PipelineState.IMAGE_PREPROCESSING)
    import cv2
    diagram_image = cv2.imread(str(artifacts["diagram"]))
    from modules.image_preprocessor import preprocess
    preprocessed = preprocess(diagram_image, debug=config.DEBUG)
    if config.DEBUG:
        cv2.imwrite(str(artifacts["preprocessed"]), preprocessed)
        logger.debug(f"Saved preprocessed image → {artifacts['preprocessed']}")

    # ── Stage 4: Circle Detection ─────────────────────────────────────────────
    emit_step(PipelineState.CIRCLE_DETECTION)
    from modules.circle_detector import detect_circles
    circles = detect_circles(preprocessed)
    logger.info(f"Detected {len(circles)} candidate circles")
    if config.DEBUG:
        _save_circle_debug(diagram_image, circles, artifacts)

    # ── Stage 5: Callout Reading ──────────────────────────────────────────────
    emit_step(PipelineState.CALLOUT_READING)
    scale = 72 / config.PDF_RENDER_DPI  # pixel → PDF point conversion
    from modules.callout_reader import read_callouts
    callouts = read_callouts(diagram_image, circles, diagram_page, scale)
    logger.info(f"Successfully read {len(callouts)} callout numbers")
    if config.DEBUG:
        import json as _json
        artifacts["ocr_results"].write_text(
            _json.dumps(callouts, indent=2), encoding="utf-8"
        )

    # ── Stage 6: BOM Extraction ───────────────────────────────────────────────
    emit_step(PipelineState.BOM_EXTRACTION)
    from modules.bom_extractor import extract_bom
    bom_rows = extract_bom(str(pdf_path), page_map["bom_page_index"])
    logger.info(f"Extracted {len(bom_rows)} BOM rows")
    if config.DEBUG:
        import json as _json
        artifacts["bom_raw"].write_text(
            _json.dumps(bom_rows, indent=2), encoding="utf-8"
        )

    # ── Stage 7: Mapping ──────────────────────────────────────────────────────
    emit_step(PipelineState.MAPPING)
    from modules.mapping_engine import map_hotspots_to_bom
    mapping_result = map_hotspots_to_bom(callouts, bom_rows)
    logger.info(
        f"Mapping complete — "
        f"{len(mapping_result['mappings'])} mapped, "
        f"{len(mapping_result['unmapped_hotspots'])} unmapped hotspots, "
        f"{len(mapping_result['unpositioned_bom_rows'])} unpositioned BOM rows"
    )
    if config.DEBUG:
        import json as _json
        artifacts["mappings_debug"].write_text(
            _json.dumps(mapping_result, indent=2), encoding="utf-8"
        )

    # ── Stage 8 (optional): LLM Validation ───────────────────────────────────
    _has_fuzzy = any(m["confidence"] < 1.0 for m in mapping_result["mappings"])
    if config.LLM_ENABLED and (mapping_result["unmapped_hotspots"] or _has_fuzzy):
        emit_step(PipelineState.LLM_VALIDATION)
        from modules.llm_resolver import resolve_with_llm
        mapping_result = resolve_with_llm(
            mapping_result=mapping_result,
            bom_rows=bom_rows,
        )
        logger.info(f"LLM validation complete - {len(mapping_result['llm_validations'])} decision(s)")
    else:
        mapping_result["llm_validations"] = []

    # ── Stage 9: Result Generation ────────────────────────────────────────────
    emit_step(PipelineState.RESULT_GENERATION)
    from modules.result_writer import write_result
    duration_ms = int((time.time() - start_time) * 1000)

    write_result(
        job_output_dir=artifacts["job_dir"],
        diagram_image_path=f"outputs/{job_id}/diagram.png",
        image_width=image_width,
        image_height=image_height,
        processing_duration_ms=duration_ms,
        page_map=page_map,
        hotspots=callouts,
        bom=bom_rows,
        mappings=mapping_result["mappings"],
        unmapped_hotspots=mapping_result["unmapped_hotspots"],
        unpositioned_bom_rows=mapping_result["unpositioned_bom_rows"],
        llm_validations=mapping_result["llm_validations"],
    )

    logger.info(f"Pipeline complete in {duration_ms}ms -> {artifacts['result']}")
    emit({"status": "done"})


def _save_circle_debug(diagram_image, circles, artifacts):
    import cv2
    debug_img = diagram_image.copy()
    for c in circles:
        cv2.circle(debug_img, (c["x"], c["y"]), c["radius"], (0, 255, 0), 2)
        cv2.circle(debug_img, (c["x"], c["y"]), 2, (0, 0, 255), 3)
    cv2.imwrite(str(artifacts["circles"]), debug_img)
    logger.debug(f"Saved circle debug image → {artifacts['circles']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Engineering PDF Analyzer — AI Worker")
    parser.add_argument("--job-id",       required=True, help="Unique job identifier (UUID)")
    parser.add_argument("--storage-path", required=True, help="Absolute path to shared storage root")
    args = parser.parse_args()

    try:
        run(job_id=args.job_id, storage_path=Path(args.storage_path))
    except NotImplementedError as exc:
        logger.error(f"Not implemented: {exc}")
        emit({"status": "error", "message": f"Module not yet implemented: {exc}"})
        sys.exit(1)
    except Exception as exc:
        logger.exception("Unhandled pipeline error")
        emit({"status": "error", "message": str(exc)})
        sys.exit(1)


if __name__ == "__main__":
    main()
