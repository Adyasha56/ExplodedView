"""
BOM Extractor

Parses the Bill of Materials page into structured rows.

Priority (deterministic-first):
  Strategy A — pdfplumber table extraction (vector/selectable-text PDFs)
  Strategy B — PaddleOCR on rendered BOM page image (scanned PDFs)
"""

import re
import time

import pdfplumber

from config import OCR_LANGUAGE, OCR_USE_ANGLE_CLS, PDF_RENDER_DPI
from utils.logger import get_logger

logger = get_logger("bom_extractor")

_HEADER_KEYWORDS = {"ref", "part", "desc", "qty", "serial", "s/n", "item", "no"}


def extract_bom(pdf_path: str, bom_page_index: int) -> list[dict]:
    """
    Returns list of { ref_no, part_no, description, qty } dicts.
    Rows with duplicate ref numbers are both kept (e.g. ref 11 appears twice).
    """
    t_start = time.perf_counter()
    logger.info("extract_bom: page %d of %s", bom_page_index, pdf_path)

    # Strategy A — pdfplumber (reliable for vector PDFs)
    rows = _pdfplumber_extract(pdf_path, bom_page_index)

    if rows:
        elapsed = (time.perf_counter() - t_start) * 1000
        logger.info(
            "extract_bom complete in %.1f ms — %d row(s) via pdfplumber",
            elapsed, len(rows),
        )
        return rows

    logger.info("  Strategy A found nothing — falling back to PaddleOCR")

    # Strategy B — PaddleOCR (scanned / image-based PDFs)
    rows = _paddleocr_extract(pdf_path, bom_page_index)

    elapsed = (time.perf_counter() - t_start) * 1000
    logger.info(
        "extract_bom complete in %.1f ms — %d row(s) via PaddleOCR",
        elapsed, len(rows),
    )
    return rows


# ── Strategy A: pdfplumber ────────────────────────────────────────────────────

def _pdfplumber_extract(pdf_path: str, page_index: int) -> list[dict]:
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        tables = page.extract_tables()

    if not tables:
        logger.info("  Strategy A: no tables found on page %d", page_index)
        return []

    main_table = max(tables, key=lambda t: len(t))
    logger.info(
        "  Strategy A: found %d table(s), using largest (%d rows × %d cols)",
        len(tables), len(main_table), len(main_table[0]) if main_table else 0,
    )

    col_map = _detect_columns(main_table)
    if col_map is None:
        logger.warning("  Strategy A: could not identify BOM columns — skipping")
        return []

    logger.info("  column map: %s", col_map)

    rows = []
    for i, raw_row in enumerate(main_table):
        if _is_header_row(raw_row):
            continue

        ref_no = _cell(raw_row, col_map.get("ref_no"))
        if not ref_no or not re.match(r"^\d+$", ref_no):
            continue  # skip blank rows and section headings

        rows.append({
            "ref_no":      ref_no,
            "part_no":     _cell(raw_row, col_map.get("part_no")),
            "description": _cell(raw_row, col_map.get("description")),
            "qty":         _parse_qty(_cell(raw_row, col_map.get("qty"))),
        })
        logger.debug("  row %d: ref=%s part=%s qty=%s", i, ref_no,
                     _cell(raw_row, col_map.get("part_no")),
                     _cell(raw_row, col_map.get("qty")))

    logger.info("  Strategy A: extracted %d BOM row(s)", len(rows))
    return rows


def _detect_columns(table: list[list]) -> dict | None:
    """
    Find the header row and map column names to indices.

    Returns a dict like { "ref_no": 0, "part_no": 1, "description": 2, "qty": 4 }
    or None if no header row is found.
    """
    for row in table[:5]:  # header is always in the first few rows
        if not _is_header_row(row):
            continue

        col_map: dict[str, int] = {}
        for i, cell in enumerate(row):
            if cell is None:
                continue
            # Collapse whitespace, newlines, and hyphens before matching.
            # pdfplumber splits wrapped header text with \n (e.g. "Q-\nty" → "qty").
            normalized = re.sub(r"[\s\-]+", "", cell.strip().lower())
            if re.search(r"ref|item", normalized):
                col_map.setdefault("ref_no", i)
            elif re.search(r"part|pn|p/n", normalized):
                col_map.setdefault("part_no", i)
            elif re.search(r"desc|name", normalized):
                col_map.setdefault("description", i)
            elif re.search(r"qty|quan", normalized):
                col_map.setdefault("qty", i)

        if "ref_no" in col_map:
            return col_map

    # Fallback: assume standard column order if no header detected
    # ref | part | description | s/n | qty
    if table and len(table[0]) >= 3:
        logger.warning("  no header row found — assuming col order: ref=0, part=1, desc=2, qty=-1")
        return {"ref_no": 0, "part_no": 1, "description": 2, "qty": len(table[0]) - 1}

    return None


def _is_header_row(row: list) -> bool:
    """
    Return True if this row looks like a column header row.

    Only checks the FIRST cell — description cells often contain words like
    "Ref." as cross-references and must not trigger a false positive.
    """
    if not row:
        return False
    first = row[0]
    if not first:
        return False
    # A data row always starts with a digit (the ref number)
    if re.match(r"^\d+", first.strip()):
        return False
    return any(kw in first.strip().lower() for kw in _HEADER_KEYWORDS)


def _cell(row: list, index: int | None) -> str | None:
    if index is None or index >= len(row):
        return None
    val = row[index]
    if val is None:
        return None
    cleaned = str(val).strip()
    return cleaned if cleaned else None


def _parse_qty(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", value)
    return int(match.group()) if match else None


# ── Strategy B: PaddleOCR ─────────────────────────────────────────────────────

def _paddleocr_extract(pdf_path: str, page_index: int) -> list[dict]:
    """
    Render the BOM page and use PaddleOCR to reconstruct table rows.
    Clusters detected text spans by Y-coordinate into rows, then assigns
    columns by X-coordinate band.

    Used only when pdfplumber finds no tables (scanned / image-based PDFs).
    """
    import fitz
    import cv2
    import numpy as np

    doc = fitz.open(pdf_path)
    pix = doc[page_index].get_pixmap(dpi=PDF_RENDER_DPI)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_angle_cls=OCR_USE_ANGLE_CLS, lang=OCR_LANGUAGE, show_log=False)
    result = ocr.ocr(img, cls=OCR_USE_ANGLE_CLS)

    if not result or not result[0]:
        logger.warning("  Strategy B: PaddleOCR returned no results")
        return []

    # Collect all text spans with their centre y and x coordinates
    spans = []
    for line in result[0]:
        bbox_pts = line[0]
        text  = line[1][0].strip()
        cx = sum(p[0] for p in bbox_pts) / 4
        cy = sum(p[1] for p in bbox_pts) / 4
        spans.append({"text": text, "cx": cx, "cy": cy})

    if not spans:
        return []

    # Cluster spans into rows by Y-coordinate (gap > 20px = new row)
    spans.sort(key=lambda s: s["cy"])
    row_clusters: list[list[dict]] = []
    current: list[dict] = [spans[0]]

    for span in spans[1:]:
        if span["cy"] - current[-1]["cy"] > 20:
            row_clusters.append(current)
            current = [span]
        else:
            current.append(span)
    row_clusters.append(current)

    # Determine column X-boundaries from the widest row (likely the header)
    header_row = max(row_clusters, key=len)
    col_xs = sorted(s["cx"] for s in header_row)

    def assign_col(cx: float) -> int:
        return min(range(len(col_xs)), key=lambda i: abs(col_xs[i] - cx))

    rows = []
    for cluster in row_clusters:
        cols: dict[int, str] = {}
        for span in sorted(cluster, key=lambda s: s["cx"]):
            col_idx = assign_col(span["cx"])
            cols[col_idx] = (cols.get(col_idx, "") + " " + span["text"]).strip()

        ref_no = cols.get(0, "").strip()
        if not ref_no or not re.match(r"^\d+$", ref_no):
            continue

        rows.append({
            "ref_no":      ref_no,
            "part_no":     cols.get(1),
            "description": cols.get(2),
            "qty":         _parse_qty(cols.get(len(col_xs) - 1)),
        })

    logger.info("  Strategy B: extracted %d BOM row(s)", len(rows))
    return rows
