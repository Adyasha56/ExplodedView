"""
Page Classifier

Discovers all diagram–BOM pairs in a PDF using structural heuristics.

Strategy:
  1. pdfplumber table detection — identify all BOM candidate pages (high cell count)
  2. Pair selection — iterate BOM candidates in page order. For each BOM page,
     the diagram is the adjacent non-table page (page before preferred, page after
     as fallback). Pages already assigned to a pair are not reused.
  3. Positional fallback — if no pairs found, return [(page 0, last page)] with
     confidence: low.

Returns a list of pair dicts so callers can process every assembly in the PDF.
Single-assembly PDFs return a list with one item.
"""

import time

import pdfplumber

from config import PAGE_CLASSIFIER_MIN_TABLE_CELLS
from utils.logger import get_logger

logger = get_logger("page_classifier")


def classify_pages(pdf_path: str) -> list[dict]:
    """
    Returns a list of { diagram_page_index, bom_page_index, classification_confidence }.
    One item per discovered assembly pair. Single-assembly PDFs return a one-item list.
    Raises ValueError if the PDF has fewer than 2 pages.
    """
    t_start = time.perf_counter()
    logger.info("classify_pages: opening %s", pdf_path)

    # ── Strategy 1: pdfplumber table detection → find all BOM candidates ──────
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

    # All pages with significant table content are BOM candidates.
    bom_candidates = sorted(
        [i for i in range(n_pages) if bom_cell_counts[i] >= PAGE_CLASSIFIER_MIN_TABLE_CELLS]
    )  # page order, not cell-count order — preserves document sequence

    logger.info(
        "  BOM candidates (page order, cell counts): %s",
        [(i, bom_cell_counts[i]) for i in bom_candidates],
    )

    # ── Strategy 2: pair each BOM page with its adjacent diagram page ─────────
    # Iterate in page order. Each BOM page claims its diagram from the adjacent
    # non-table page. Pages already claimed are not reused across pairs.
    pairs: list[dict] = []
    used_pages: set[int] = set()

    for bom_idx in bom_candidates:
        if bom_idx in used_pages:
            continue

        diagram_idx = None

        # Prefer the page immediately before (standard [diagram, BOM] layout)
        prev = bom_idx - 1
        if (
            prev >= 0
            and prev not in used_pages
            and bom_cell_counts[prev] < PAGE_CLASSIFIER_MIN_TABLE_CELLS
        ):
            diagram_idx = prev

        # Fallback: check page after
        if diagram_idx is None:
            nxt = bom_idx + 1
            if (
                nxt < n_pages
                and nxt not in used_pages
                and bom_cell_counts[nxt] < PAGE_CLASSIFIER_MIN_TABLE_CELLS
            ):
                diagram_idx = nxt

        if diagram_idx is not None:
            pairs.append({
                "diagram_page_index":        diagram_idx,
                "bom_page_index":            bom_idx,
                "classification_confidence": "high",
            })
            used_pages.add(diagram_idx)
            used_pages.add(bom_idx)
            logger.info(
                "  Assembly %d: diagram=page%d, bom=page%d (%d cells)",
                len(pairs) - 1, diagram_idx, bom_idx, bom_cell_counts[bom_idx],
            )
        else:
            logger.warning(
                "  BOM page %d has no available adjacent non-table page — skipping",
                bom_idx,
            )

    # ── Strategy 3: positional fallback ───────────────────────────────────────
    if not pairs:
        logger.warning(
            "  No pairs found (no table detected above %d-cell threshold or no "
            "adjacent diagram page). Falling back to page 0=diagram, page %d=BOM — "
            "confidence: low",
            PAGE_CLASSIFIER_MIN_TABLE_CELLS,
            n_pages - 1,
        )
        pairs.append({
            "diagram_page_index":        0,
            "bom_page_index":            n_pages - 1,
            "classification_confidence": "low",
        })

    elapsed = (time.perf_counter() - t_start) * 1000
    logger.info(
        "classify_pages complete in %.1f ms — %d assembly pair(s) found",
        elapsed, len(pairs),
    )

    return pairs
