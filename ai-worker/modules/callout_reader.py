"""
Callout Reader

Extracts the number printed inside each detected callout region.

Priority (deterministic-first):
  Strategy A — PyMuPDF full-page text scan
                Works when callout numbers are stored as embedded text (text-layer PDFs).
                Fast and perfectly accurate.

  Strategy B — Full-image PaddleOCR scan (2 passes)
                Pass 1: Overlapping horizontal tiles across the full image.
                        Finds the majority of callout numbers.
                Pass 2: Seed-expansion — tight crops centred on each callout
                        found in Pass 1. Catches numbers clustered in the same
                        region that the broad tile scan misses due to detection
                        window interference (e.g. digits 7, 8, 4 clustered near 13).

  Undetected callouts are NOT fabricated with placeholder coordinates.
  The mapping engine reports them in unmappedBomRows; the frontend lists
  them without overlay pins.

Known failure modes addressed in this implementation:
  - Leader-line contamination: "10-" or "-6" → stripped from both ends
  - Dense cluster occlusion: seed-expansion with tight 80px crops finds
    adjacent digits missed by the 1461px tile scan
  - Bobcat logo watermark overlap: tight crop padding (40px) isolates
    digits from adjacent logo bounding boxes
"""

import re
import time

import cv2
import numpy as np

from config import (
    OCR_LANGUAGE,
    OCR_USE_ANGLE_CLS,
    PDF_RENDER_DPI,
)
from utils.logger import get_logger

logger = get_logger("callout_reader")

_DIGIT_RE = re.compile(r"^\d{1,2}$")

_ocr_engine = None

# Radius (px) around each seed callout searched in Pass 2.
_SEED_SEARCH_RADIUS = 350

# Minimum dimension (px) a crop is upscaled to before OCR.
_CROP_MIN_DIM = 150

# Minimum OCR confidence accepted in the broad tile pass.
_PASS1_MIN_SCORE = 0.50

# Minimum OCR confidence accepted in the tight seed-expansion pass.
# Lower because upscaled tight crops have sparser context for the recogniser.
_PASS2_MIN_SCORE = 0.40


def read_callouts(
    diagram_image: np.ndarray,
    circles: list[dict],
    pdf_page,
    image_to_pdf_scale: float,
) -> list[dict]:
    """
    Returns list of { x, y, radius, number, extraction_method } for detected callouts.
    Undetected callouts have no entry — they surface as unpositionedBomRows.
    """
    t_start = time.perf_counter()
    logger.info("read_callouts: diagram %dx%d", diagram_image.shape[1], diagram_image.shape[0])

    # Strategy A — PyMuPDF text layer (free, zero error risk)
    if pdf_page is not None:
        results = _pymupdf_full_page_scan(pdf_page)
        if results:
            results = _deduplicate(results)
            elapsed = (time.perf_counter() - t_start) * 1000
            logger.info(
                "read_callouts complete in %.1f ms — %d callout(s) via PyMuPDF: %s",
                elapsed, len(results), sorted(int(r["number"]) for r in results),
            )
            return results
        logger.info("  Strategy A: 0 text callouts — falling back to OCR")

    # Strategy B — PaddleOCR (2 passes)
    results = _paddleocr_scan(diagram_image)
    results = _deduplicate(results)

    elapsed = (time.perf_counter() - t_start) * 1000
    logger.info(
        "read_callouts complete in %.1f ms — %d callout(s) via PaddleOCR: %s",
        elapsed, len(results), sorted(int(r["number"]) for r in results),
    )
    return results


# ── Strategy A ────────────────────────────────────────────────────────────────

def _pymupdf_full_page_scan(pdf_page) -> list[dict]:
    scale = PDF_RENDER_DPI / 72
    callouts = []
    seen: set[str] = set()

    for block in pdf_page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span["text"].strip()
                if not _DIGIT_RE.match(text) or text in seen:
                    continue
                bbox = span["bbox"]
                cx = int(((bbox[0] + bbox[2]) / 2) * scale)
                cy = int(((bbox[1] + bbox[3]) / 2) * scale)
                r  = max(int(((bbox[3] - bbox[1]) / 2) * scale), 10)
                callouts.append({"x": cx, "y": cy, "radius": r,
                                  "number": text, "extraction_method": "pymupdf"})
                seen.add(text)
                logger.debug("  PyMuPDF: '%s' at (%d,%d)", text, cx, cy)

    logger.info("  Strategy A: found %d standalone digit(s)", len(callouts))
    return callouts


# ── Strategy B ────────────────────────────────────────────────────────────────

def _paddleocr_scan(diagram_image: np.ndarray) -> list[dict]:
    h, w = diagram_image.shape[:2]
    top_cut    = int(h * 0.03)
    bottom_cut = int(h * 0.97)
    engine     = _get_ocr_engine()

    found: dict[str, dict] = {}  # number → best candidate

    # ── Pass 1: overlapping horizontal tiles ──────────────────────────────────
    tile_h    = h // 3
    overlap   = tile_h // 4
    starts    = [0, tile_h - overlap, 2 * tile_h - 2 * overlap]
    ends      = [s + tile_h + overlap for s in starts]
    ends[-1]  = h

    for i, (y0, y1) in enumerate(zip(starts, ends)):
        tile       = diagram_image[y0:y1, :]
        ocr_result = engine.ocr(tile, cls=OCR_USE_ANGLE_CLS)
        if not ocr_result or not ocr_result[0]:
            continue

        logger.info("  Pass 1 tile %d/%d rows %d–%d: %d box(es)",
                    i + 1, len(starts), y0, y1, len(ocr_result[0]))

        for line in ocr_result[0]:
            bbox_pts = line[0]
            text     = _clean(line[1][0])
            score    = line[1][1]

            if not _DIGIT_RE.match(text) or score < _PASS1_MIN_SCORE:
                continue

            cx = int(sum(p[0] for p in bbox_pts) / 4)
            cy = int(sum(p[1] for p in bbox_pts) / 4) + y0

            if not (top_cut <= cy <= bottom_cut):
                continue

            bh = max(p[1] for p in bbox_pts) - min(p[1] for p in bbox_pts)
            r  = max(int(bh / 2), 10)
            _keep_best(found, text, cx, cy, r, score, "paddleocr")

    logger.info("  Pass 1 complete: %d callout(s): %s",
                len(found), sorted(int(k) for k in found))

    # ── Pass 2: seed-expansion around each found callout ─────────────────────
    # For every callout found in Pass 1, scan a _SEED_SEARCH_RADIUS window
    # around it with tight crops. This catches digits that share a local
    # neighbourhood with an already-detected number but were suppressed by the
    # broader tile detection window (e.g. 7, 8, 4 near 13).
    seeds_before = len(found)

    for seed_num, seed in list(found.items()):
        sx, sy = seed["x"], seed["y"]
        rx0 = max(0, sx - _SEED_SEARCH_RADIUS)
        ry0 = max(0, sy - _SEED_SEARCH_RADIUS)
        rx1 = min(w, sx + _SEED_SEARCH_RADIUS)
        ry1 = min(h, sy + _SEED_SEARCH_RADIUS)

        region = diagram_image[ry0:ry1, rx0:rx1]
        if region.size == 0:
            continue

        # Upscale small regions so digits occupy enough pixels for detection
        rh, rw     = region.shape[:2]
        scale_up   = max(1.0, _CROP_MIN_DIM / min(rh, rw))
        if scale_up > 1.0:
            region = cv2.resize(region,
                                (int(rw * scale_up), int(rh * scale_up)),
                                interpolation=cv2.INTER_CUBIC)

        ocr_result = engine.ocr(region, cls=OCR_USE_ANGLE_CLS)
        if not ocr_result or not ocr_result[0]:
            continue

        for line in ocr_result[0]:
            bbox_pts = line[0]
            text     = _clean(line[1][0])
            score    = line[1][1]

            if not _DIGIT_RE.match(text) or score < _PASS2_MIN_SCORE:
                continue
            if text in found:
                _keep_best(found, text,
                           int(sum(p[0] for p in bbox_pts) / 4 / scale_up) + rx0,
                           int(sum(p[1] for p in bbox_pts) / 4 / scale_up) + ry0,
                           max(int((max(p[1] for p in bbox_pts) -
                                    min(p[1] for p in bbox_pts)) / 2 / scale_up), 10),
                           score, "paddleocr")
                continue

            cx = int(sum(p[0] for p in bbox_pts) / 4 / scale_up) + rx0
            cy = int(sum(p[1] for p in bbox_pts) / 4 / scale_up) + ry0

            if not (top_cut <= cy <= bottom_cut):
                continue

            bh = max(p[1] for p in bbox_pts) - min(p[1] for p in bbox_pts)
            r  = max(int(bh / 2 / scale_up), 10)
            _keep_best(found, text, cx, cy, r, score, "paddleocr")
            logger.debug("  Pass 2: '%s' (%.2f) at (%d,%d) via seed #%s (%d,%d)",
                         text, score, cx, cy, seed_num, sx, sy)

    new_in_pass2 = len(found) - seeds_before
    logger.info("  Pass 2 added %d new callout(s). Total: %s",
                new_in_pass2, sorted(int(k) for k in found))

    return list(found.values())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    """
    Strip leading AND trailing non-digit characters.
      "10-"  → "10"   trailing dash from adjacent leader line
      "-6"   → "6"    prefix dash from leader line on the left
      "-13-" → "13"   both sides
    """
    return re.sub(r"^\D+|\D+$", "", text.strip())


def _keep_best(found: dict, text: str, cx: int, cy: int,
               r: int, score: float, method: str) -> None:
    if text not in found or score > found[text].get("score", 0):
        found[text] = {"x": cx, "y": cy, "radius": r,
                       "number": text, "extraction_method": method,
                       "score": round(score, 3)}


_METHOD_PRIORITY = {"pymupdf": 0, "paddleocr": 1}


def _deduplicate(callouts: list[dict]) -> list[dict]:
    """Keep the highest-confidence entry per callout number."""
    best: dict[str, dict] = {}
    for c in callouts:
        num  = c["number"]
        prio = _METHOD_PRIORITY.get(c["extraction_method"], 99)
        if num not in best:
            best[num] = c
        else:
            best_prio = _METHOD_PRIORITY.get(best[num]["extraction_method"], 99)
            if prio < best_prio or (
                prio == best_prio and c.get("score", 0) > best[num].get("score", 0)
            ):
                best[num] = c
    return list(best.values())


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        logger.info("  initialising PaddleOCR engine")
        from paddleocr import PaddleOCR
        _ocr_engine = PaddleOCR(
            use_angle_cls=OCR_USE_ANGLE_CLS,
            lang=OCR_LANGUAGE,
            det_limit_side_len=3600,
            det_db_thresh=0.2,
        )
    return _ocr_engine
