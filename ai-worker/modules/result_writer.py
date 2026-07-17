"""
Result Writer

Serialises the final pipeline output to result.json.
No logic, no decisions — assembly and serialisation only.

Field names are converted from Python snake_case to camelCase at this
serialisation boundary so the JSON matches the Mongoose Result schema exactly.

diagramImagePath inside each assembly is stored as an artifact-relative path
(e.g. "outputs/<jobId>/assembly_0/diagram.png"). The Node.js bridge transforms
these to Express static URLs (/static/outputs/<jobId>/assembly_0/diagram.png)
before persisting the Result document.
"""

import json
import time
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("result_writer")


def write_result(
    job_output_dir: Path,
    processing_duration_ms: int,
    total_pdf_pages: int,
    assemblies: list[dict],
) -> Path:
    """Write the structured result to <job_output_dir>/result.json."""
    t_start = time.perf_counter()

    result = {
        "processingDurationMs": processing_duration_ms,
        "totalPdfPages":        total_pdf_pages,
        "assemblies": [_serialise_assembly(a) for a in assemblies],
    }

    out_path = job_output_dir / "result.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    elapsed = (time.perf_counter() - t_start) * 1000
    logger.info(
        "write_result: wrote %d bytes to %s in %.1f ms",
        out_path.stat().st_size, out_path, elapsed,
    )

    return out_path


def _serialise_assembly(a: dict) -> dict:
    page_map = a["page_map"]
    return {
        "assemblyIndex":      a["assembly_index"],
        "pageMap": {
            "diagramPageIndex":          page_map["diagram_page_index"],
            "bomPageIndex":              page_map["bom_page_index"],
            "classificationConfidence":  page_map["classification_confidence"],
        },
        "diagramImagePath":   a["diagram_image_path"],
        "imageWidth":         a["image_width"],
        "imageHeight":        a["image_height"],
        "totalParts":         a["total_parts"],
        "hotspots":           [_serialise_hotspot(h) for h in a["hotspots"]],
        "bom":                [_serialise_bom_row(r) for r in a["bom"]],
        "mappings":           [_serialise_mapping(m) for m in a["mappings"]],
        "unmappedHotspots":   [_serialise_hotspot(h) for h in a["unmapped_hotspots"]],
        "unpositionedBomRows":[_serialise_bom_row(r) for r in a["unpositioned_bom_rows"]],
        "notShownBomRows":    [_serialise_bom_row(r) for r in a["not_shown_bom_rows"]],
        "llmValidations":     a["llm_validations"],
    }


def _serialise_hotspot(h: dict) -> dict:
    return {
        "number":           h["number"],
        "x":                h["x"],
        "y":                h["y"],
        "radius":           h["radius"],
        "extractionMethod": h["extraction_method"],
    }


def _serialise_bom_row(r: dict) -> dict:
    return {
        "refNo":       r["ref_no"],
        "partNo":      r.get("part_no"),
        "description": r.get("description"),
        "qty":         r.get("qty"),
    }


def _serialise_mapping(m: dict) -> dict:
    return {
        "hotspotNumber": m["hotspot_number"],
        "x":             m["x"],
        "y":             m["y"],
        "radius":        m["radius"],
        "confidence":    m["confidence"],
        "bom":           [_serialise_bom_row(r) for r in m["bom"]],
    }
