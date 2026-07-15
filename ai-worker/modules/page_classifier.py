"""
Page Classifier

Determines which page in the PDF is the exploded-view diagram and which
is the BOM table, using structural heuristics — no ML required.

Priority (deterministic-first):
  1. pdfplumber table detection  → BOM candidate (page with most table cells)
  2. PyMuPDF path density        → diagram candidate (page with most vector paths)
  3. Positional fallback         → first page = diagram, last page = BOM
"""

import time

import fitz  # PyMuPDF
import pdfplumber

from config import PAGE_CLASSIFIER_MIN_TABLE_CELLS
from utils.logger import get_logger

logger = get_logger("page_classifier")


def classify_pages(pdf_path: str) -> dict:
    """
    Returns { diagram_page_index, bom_page_index, classification_confidence }.
    classification_confidence is "low" when the positional fallback was used.
    Raises ValueError if the PDF has fewer than 2 pages.
    """
    t_start = time.perf_counter()
    logger.info("classify_pages: opening %s", pdf_path)

    # ── Strategy 1: pdfplumber table detection → BOM candidate ────────────────
    bom_page_index = None
    bom_cell_counts = []

    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        if n_pages < 2:
            raise ValueError(f"PDF has only {n_pages} page(s); expected at least 2")

        for i, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            cell_count = sum(
                len(row) for table in tables for row in table if row is not None
            )
            bom_cell_counts.append(cell_count)
            logger.debug("  page %d: %d table cells detected", i, cell_count)

    best_bom_page = max(range(n_pages), key=lambda i: bom_cell_counts[i])
    if bom_cell_counts[best_bom_page] >= PAGE_CLASSIFIER_MIN_TABLE_CELLS:
        bom_page_index = best_bom_page
        logger.info(
            "  BOM candidate: page %d (%d cells) — Strategy 1 (table detection)",
            bom_page_index,
            bom_cell_counts[bom_page_index],
        )

    # ── Strategy 2: PyMuPDF path density → diagram candidate ──────────────────
    diagram_page_index = None
    path_counts = []

    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            paths = page.get_drawings()
            path_counts.append(len(paths))
            logger.debug("  page %d: %d vector paths detected", i, len(paths))

    best_diagram_page = max(range(n_pages), key=lambda i: path_counts[i])

    # Prefer the page with the most vector paths, but never pick the BOM page
    # when a separate BOM page was confidently detected.
    if bom_page_index is not None and best_diagram_page != bom_page_index:
        diagram_page_index = best_diagram_page
    elif bom_page_index is not None:
        # BOM page has the most paths (unusual); pick next best
        sorted_by_paths = sorted(range(n_pages), key=lambda i: path_counts[i], reverse=True)
        for candidate in sorted_by_paths:
            if candidate != bom_page_index:
                diagram_page_index = candidate
                break
    else:
        diagram_page_index = best_diagram_page

    if diagram_page_index is not None:
        logger.info(
            "  Diagram candidate: page %d (%d paths) — Strategy 2 (path density)",
            diagram_page_index,
            path_counts[diagram_page_index],
        )

    # ── Strategy 3: positional fallback ───────────────────────────────────────
    confidence = "high"

    if bom_page_index is None:
        bom_page_index = n_pages - 1
        diagram_page_index = 0
        confidence = "low"
        logger.warning(
            "  No table detected above threshold (%d cells). "
            "Falling back to page 0=diagram, page %d=BOM — confidence: low",
            PAGE_CLASSIFIER_MIN_TABLE_CELLS,
            bom_page_index,
        )
    elif diagram_page_index is None:
        # Should never happen for n_pages >= 2, but guard anyway
        diagram_page_index = 0 if bom_page_index != 0 else 1
        confidence = "low"
        logger.warning("  Diagram page could not be determined; using fallback index %d", diagram_page_index)

    if diagram_page_index == bom_page_index:
        diagram_page_index = 0 if bom_page_index != 0 else 1
        confidence = "low"
        logger.warning("  diagram and BOM resolved to same page; forced diagram to page %d", diagram_page_index)

    elapsed = (time.perf_counter() - t_start) * 1000
    logger.info(
        "classify_pages complete in %.1f ms — diagram=page%d, bom=page%d, confidence=%s",
        elapsed,
        diagram_page_index,
        bom_page_index,
        confidence,
    )

    return {
        "diagram_page_index": diagram_page_index,
        "bom_page_index": bom_page_index,
        "classification_confidence": confidence,
    }
