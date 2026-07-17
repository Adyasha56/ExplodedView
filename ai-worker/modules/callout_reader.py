"""
Callout Reader

Extracts the number printed inside each detected callout region.

Strategy priority (deterministic-first):

  Strategy A — PyMuPDF full-page text scan
                Works when callout numbers are stored as embedded text (text-layer PDFs).
                Fast and perfectly accurate. Returns immediately if callouts found.

  Strategy B — Full-image PaddleOCR scan (2 passes)
                Pass 1: Overlapping horizontal tiles across the full image.
                Pass 2: Seed-expansion — tight crops centred on each Pass 1 callout.
                        Catches numbers clustered in the same region that the broad
                        tile scan misses due to detection window interference.

  Strategy C — Per-circle targeted OCR (recovery pass)
                For each accepted circle from the circle detector, crops and OCRs
                individually. Recovers callouts missed by the broad tile scan in dense
                clusters. Uses circle geometry as canonical coordinates rather than OCR
                bounding boxes. Fires only when the circle list is non-empty.

  False-positive filtering (circled-callout documents only):
                After all OCR passes, assess whether the page uses circled callouts by
                measuring what fraction of OCR hits spatially align with detected circles.
                If the alignment evidence is strong enough, reject OCR hits that have no
                spatial relationship to any accepted circle (e.g. page numbers, footers).
                Pages without strong circle evidence (plain-number or leader-line style)
                are not filtered.

Undetected callouts produce no entry. They surface as unpositionedBomRows.
"""

import math
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

# ── Pass 1 / Pass 2 tuning 
_SEED_SEARCH_RADIUS = 350
_CROP_MIN_DIM       = 150
_PASS1_MIN_SCORE    = 0.50
_PASS2_MIN_SCORE    = 0.40

# ── Strategy C tuning 
# Extra pixels beyond the circle radius added to each side of the crop.
_STRATEGY_C_PADDING_PX  = 8
# Tight crops are well-isolated; a slightly lower threshold is acceptable.
_STRATEGY_C_MIN_SCORE   = 0.35

# ── Circled-callout page style detection 
# Fewer detected circles than this → skip classification entirely.
_CIRCLED_CALLOUT_MIN_CIRCLES          = 3
# Fraction of OCR hits that must align with a circle to confirm circled-callout style.
# Set high (0.85) because the circle detector has a meaningful miss rate — valid
# callouts whose circles weren't detected appear non-aligned and must not be filtered.
_CIRCLED_CALLOUT_ALIGNMENT_THRESHOLD  = 0.85
# A hit "aligns" with a circle when its distance to the circle centre ≤ radius × this.
_CIRCLED_CALLOUT_PROXIMITY_MULTIPLIER = 2.5


def read_callouts(
    diagram_image: np.ndarray,
    circles: list[dict],
    pdf_page,
    image_to_pdf_scale: float,
    crop_y0: int = 0,
) -> list[dict]:
    """
    Returns list of { x, y, radius, number, extraction_method } for detected callouts.
    Undetected callouts have no entry — they surface as unpositionedBomRows.
    """
    t_start = time.perf_counter()
    logger.info("read_callouts: diagram %dx%d", diagram_image.shape[1], diagram_image.shape[0])

    # Strategy A — PyMuPDF text layer
    if pdf_page is not None:
        results = _pymupdf_full_page_scan(pdf_page, crop_y0=crop_y0)
        if results:
            results = _deduplicate(results)
            elapsed = (time.perf_counter() - t_start) * 1000
            logger.info(
                "read_callouts complete in %.1f ms — %d callout(s) via PyMuPDF: %s",
                elapsed, len(results), sorted(int(r["number"]) for r in results),
            )
            return results
        logger.info("  Strategy A: 0 text callouts — falling back to OCR")

    # Strategy B (Pass 1 + Pass 2) + Strategy C + filtering
    results = _paddleocr_scan(diagram_image, circles)
    results = _deduplicate(results)

    elapsed = (time.perf_counter() - t_start) * 1000
    logger.info(
        "read_callouts complete in %.1f ms — %d callout(s) via PaddleOCR: %s",
        elapsed, len(results), sorted(int(r["number"]) for r in results),
    )
    return results


# ── Strategy A 

def _pymupdf_full_page_scan(pdf_page, crop_y0: int = 0) -> list[dict]:
    scale         = PDF_RENDER_DPI / 72
    page_h_px     = pdf_page.rect.height * scale
    # After cropping, valid Y in cropped-image space = 0 .. (page_h_px - crop_y0).
    # We apply a further 10% inner-margin filter on the cropped height.
    cropped_h_px  = page_h_px - crop_y0
    top_cut_px    = cropped_h_px * 0.03
    bottom_cut_px = cropped_h_px * 0.97
    callouts      = []
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
                # Convert from full-page pixel space to cropped-image pixel space
                cy = int(((bbox[1] + bbox[3]) / 2) * scale) - crop_y0
                if cy < 0 or cy < top_cut_px or cy > bottom_cut_px:
                    logger.debug("  PyMuPDF: skipping '%s' at cy=%d (outside crop zone)", text, cy)
                    continue
                r  = max(int(((bbox[3] - bbox[1]) / 2) * scale), 10)
                callouts.append({"x": cx, "y": cy, "radius": r,
                                  "number": text, "extraction_method": "pymupdf"})
                seen.add(text)
                logger.debug("  PyMuPDF: '%s' at (%d,%d)", text, cx, cy)

    logger.info("  Strategy A: found %d standalone digit(s)", len(callouts))
    return callouts


# ── Strategy B + C 

def _paddleocr_scan(diagram_image: np.ndarray, circles: list[dict]) -> list[dict]:
    h, w       = diagram_image.shape[:2]
    top_cut    = int(h * 0.03)
    bottom_cut = int(h * 0.97)
    engine     = _get_ocr_engine()

    found: dict[str, dict] = {}

    # ── Pass 1: overlapping horizontal tiles 
    tile_h  = h // 3
    overlap = tile_h // 4
    starts  = [0, tile_h - overlap, 2 * tile_h - 2 * overlap]
    ends    = [s + tile_h + overlap for s in starts]
    ends[-1] = h

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

    # ── Pass 2: seed-expansion around each found callout 
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

        rh, rw   = region.shape[:2]
        scale_up = max(1.0, _CROP_MIN_DIM / min(rh, rw))
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

    logger.info("  Pass 2 added %d new callout(s). Total: %s",
                len(found) - seeds_before, sorted(int(k) for k in found))

    # ── Strategy C: per-circle targeted OCR 
    _per_circle_ocr(diagram_image, circles, found, engine)

    # ── Circled-callout style detection and false-positive filtering 
    results = list(found.values())
    results = _filter_non_callout_text(results, circles)

    return results


def _per_circle_ocr(
    diagram_image: np.ndarray,
    circles: list[dict],
    found: dict[str, dict],
    engine,
) -> None:
    """
    Recovery pass: OCR each accepted circle individually.

    Crops a tight window around each detected circle, upscales, and OCRs.
    Among all digit detections within the crop, selects the one closest to the
    crop centre (most likely the callout number, not an adjacent artefact).

    Only adds callouts NOT already found by Pass 1/2. Does not override
    coordinates from existing hits — tile-scan results may have come from
    a different (possibly better) position for the same digit.

    Uses circle centre as canonical coordinates, which are more reliable than
    OCR bounding-box centres in dense clusters.
    """
    if not circles:
        return

    h, w             = diagram_image.shape[:2]
    border_cut_top   = int(h * 0.03)
    border_cut_y     = int(h * 0.97)
    recovered        = 0

    for circle in circles:
        if circle["y"] < border_cut_top or circle["y"] > border_cut_y:
            logger.debug(
                "  Strategy C: skipping border-area circle at (%d,%d) r=%d",
                circle["x"], circle["y"], circle["radius"],
            )
            continue
        cx, cy, r = circle["x"], circle["y"], circle["radius"]
        pad = r + _STRATEGY_C_PADDING_PX
        x0  = max(0, cx - pad)
        y0  = max(0, cy - pad)
        x1  = min(w, cx + pad)
        y1  = min(h, cy + pad)
        crop = diagram_image[y0:y1, x0:x1]
        if crop.size == 0:
            continue

        ch, cw   = crop.shape[:2]
        scale_up = max(1.0, _CROP_MIN_DIM / min(ch, cw))
        if scale_up > 1.0:
            crop = cv2.resize(crop,
                              (int(cw * scale_up), int(ch * scale_up)),
                              interpolation=cv2.INTER_CUBIC)

        ocr_result = engine.ocr(crop, cls=OCR_USE_ANGLE_CLS)
        if not ocr_result or not ocr_result[0]:
            continue

        # Among all digit hits in this crop, pick the one closest to the crop centre.
        # Dividing by scale_up converts back to original-resolution coordinates.
        crop_cx_orig = cw / 2.0
        crop_cy_orig = ch / 2.0

        best_text  = None
        best_score = 0.0
        best_dist  = float("inf")

        for line in ocr_result[0]:
            bbox_pts = line[0]
            text     = _clean(line[1][0])
            score    = line[1][1]

            if not _DIGIT_RE.match(text) or score < _STRATEGY_C_MIN_SCORE:
                continue

            box_cx = sum(p[0] for p in bbox_pts) / 4 / scale_up
            box_cy = sum(p[1] for p in bbox_pts) / 4 / scale_up
            dist   = math.sqrt((box_cx - crop_cx_orig) ** 2 + (box_cy - crop_cy_orig) ** 2)

            if best_text is None or score > best_score or (
                abs(score - best_score) < 0.05 and dist < best_dist
            ):
                best_text  = text
                best_score = score
                best_dist  = dist

        if best_text is None:
            continue

        # Normalise: strip leading zeros ("06" → "6"). Reject bare "0" (invalid callout).
        best_text = best_text.lstrip("0") or "0"
        if best_text == "0":
            logger.debug("  Strategy C: rejected '0' (invalid callout number) at circle (%d,%d)", cx, cy)
            continue

        if best_text not in found:
            found[best_text] = {
                "x": cx, "y": cy, "radius": r,
                "number": best_text, "extraction_method": "paddleocr",
                "score": round(best_score, 3),
            }
            recovered += 1
            logger.debug(
                "  Strategy C: recovered '%s' (%.2f) at circle (%d,%d) r=%d",
                best_text, best_score, cx, cy, r,
            )

    logger.info(
        "  Strategy C: recovered %d new callout(s). Total after C: %s",
        recovered, sorted(int(k) for k in found),
    )


def _filter_non_callout_text(
    results: list[dict],
    circles: list[dict],
) -> list[dict]:
    """
    Reject OCR hits that are not associated with any detected callout circle,
    but only when the page is confidently identified as circled-callout style.

    Classification: compute what fraction of OCR hits spatially align with a
    detected circle (distance to nearest circle centre ≤ radius × proximity
    multiplier). If the majority align, the page uses circled callouts and any
    non-aligned hit is non-callout text (page number, title block, footer, etc.).

    Pages with fewer than _CIRCLED_CALLOUT_MIN_CIRCLES detected circles are not
    classified — plain-number and leader-line documents pass through unfiltered.
    """
    if len(circles) < _CIRCLED_CALLOUT_MIN_CIRCLES or not results:
        return results

    def nearest_circle_ratio(hit: dict) -> float:
        """Minimum (distance / radius) across all circles — < 1.5 means aligned."""
        hx, hy = hit["x"], hit["y"]
        return min(
            math.sqrt((hx - c["x"]) ** 2 + (hy - c["y"]) ** 2) / c["radius"]
            for c in circles
        )

    ratios         = [nearest_circle_ratio(r) for r in results]
    aligned_flags  = [ratio <= _CIRCLED_CALLOUT_PROXIMITY_MULTIPLIER for ratio in ratios]
    aligned_count  = sum(aligned_flags)
    alignment_ratio = aligned_count / len(results)

    logger.info(
        "  Circle-callout detection: %d/%d hits align with circles "
        "(ratio=%.2f, threshold=%.2f)",
        aligned_count, len(results), alignment_ratio, _CIRCLED_CALLOUT_ALIGNMENT_THRESHOLD,
    )

    # Only filter when the evidence is very strong (near-unanimous alignment).
    # The circle detector has a meaningful miss rate — valid callout circles are
    # sometimes not detected, so their OCR hits appear non-aligned through no fault
    # of the callout reader. Over-filtering is worse than under-filtering: a wrongly
    # rejected callout becomes a silently missing hotspot, whereas a wrongly kept hit
    # becomes an unmapped hotspot the mapping engine handles gracefully.
    if alignment_ratio >= _CIRCLED_CALLOUT_ALIGNMENT_THRESHOLD:
        logger.info("  Circled-callout page style confirmed (strong) — filtering non-aligned OCR hits")
        filtered = [r for r, aligned in zip(results, aligned_flags) if aligned]
        rejected = [r["number"] for r, aligned in zip(results, aligned_flags) if not aligned]
        if rejected:
            logger.info("  Rejected non-callout text: %s", rejected)
        return filtered

    logger.info(
        "  Circled-callout page style NOT confirmed (ratio=%.2f < %.2f) — no filtering applied",
        alignment_ratio, _CIRCLED_CALLOUT_ALIGNMENT_THRESHOLD,
    )
    return results


# ── Helpers 

def _clean(text: str) -> str:
    """Strip leading and trailing non-digit characters from OCR output."""
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
