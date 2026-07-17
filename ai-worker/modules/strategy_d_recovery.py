"""
Strategy D — Enhanced Unresolved-Circle Recovery

For each circle that has no spatially proximate callout after Strategies A/B/C,
try multiple preprocessing variants with PaddleOCR and accept a digit only if it
matches a known recovery target (a BOM ref that is still unpositioned).

Recovery is strictly target-gated: digits NOT in the target set are never accepted,
preventing false positives from table numbers, page numbers, etc.
"""

import math
import re

import cv2
import numpy as np

from config import OCR_USE_ANGLE_CLS
from utils.logger import get_logger

logger = get_logger("strategy_d")

# ── Tuning constants ───────────────────────────────────────────────────────────
_DIGIT_RE = re.compile(r"^\d{1,2}$")

# A circle is "resolved" if an existing callout lies within this many radii.
_RESOLVED_PROXIMITY_RATIO = 1.5

# Crop radius multiplier and minimum crop dimension.
_CROP_PADDING_MULTIPLIER = 2.0
_CROP_MIN_DIM = 128

# Accept a detection only if it meets this minimum confidence.
_MIN_CONFIDENCE = 0.35

# Minimum number of preprocessing variants that must agree on the same digit.
_MIN_VARIANT_VOTES = 1


# ── Public entry point ─────────────────────────────────────────────────────────

def recover_unresolved_circles(
    diagram_image: np.ndarray,
    circles: list[dict],
    existing_callouts: list[dict],
    bom_rows: list[dict],
) -> list[dict]:
    """
    Returns a list of recovered callout dicts (same schema as callout_reader output).

    Only recovers BOM refs that are:
      1. Present in the BOM with no "NOT SHOWN" marker
      2. Not already detected by Strategies A/B/C

    Only considers circles that have no existing callout within _RESOLVED_PROXIMITY_RATIO
    radii of the circle centre.
    """
    targets = _compute_recovery_targets(bom_rows, existing_callouts)
    if not targets:
        logger.info("Strategy D: no recovery targets — all BOM refs already detected")
        return []

    logger.info("Strategy D: recovery targets = %s", sorted(targets, key=lambda x: int(x) if x.isdigit() else 0))

    unresolved = _find_unresolved_circles(circles, existing_callouts)
    logger.info(
        "Strategy D: %d circle(s) total, %d unresolved (no nearby callout)",
        len(circles), len(unresolved),
    )

    if not unresolved:
        return []

    engine = _get_ocr_engine()
    h, w = diagram_image.shape[:2]

    recovered: list[dict] = []
    already_recovered: set[str] = set()

    for idx, circle in enumerate(unresolved):
        result = _try_circle(diagram_image, circle, targets, engine, w, h, idx)
        if result and result["number"] not in already_recovered:
            recovered.append(result)
            already_recovered.add(result["number"])
            targets = targets - {result["number"]}  # don't double-recover
            logger.info(
                "Strategy D: recovered ref=%s at circle(%d,%d) r=%d via %d variant vote(s)",
                result["number"], circle["x"], circle["y"], circle["radius"],
                result.get("_votes", "?"),
            )

    logger.info(
        "Strategy D: recovered %d ref(s): %s",
        len(recovered),
        [r["number"] for r in recovered],
    )
    return recovered


# ── Internal helpers ───────────────────────────────────────────────────────────

def _compute_recovery_targets(bom_rows: list[dict], existing_callouts: list[dict]) -> set[str]:
    def is_not_shown(row: dict) -> bool:
        return "NOT SHOWN" in (row.get("description") or "").upper()

    def normalise(ref) -> str:
        return str(ref).strip().lstrip("0") or "0"

    visible_refs = {normalise(r["ref_no"]) for r in bom_rows if not is_not_shown(r)}
    detected     = {normalise(c["number"]) for c in existing_callouts}
    return visible_refs - detected


def _find_unresolved_circles(
    circles: list[dict],
    existing_callouts: list[dict],
) -> list[dict]:
    unresolved = []
    for circle in circles:
        cx, cy, r = circle["x"], circle["y"], circle["radius"]
        near = False
        for callout in existing_callouts:
            dist = math.sqrt((cx - callout["x"]) ** 2 + (cy - callout["y"]) ** 2)
            if dist <= r * _RESOLVED_PROXIMITY_RATIO:
                near = True
                break
        if not near:
            unresolved.append(circle)
    return unresolved


def _try_circle(
    image: np.ndarray,
    circle: dict,
    recovery_targets: set[str],
    engine,
    img_w: int,
    img_h: int,
    idx: int,
) -> dict | None:
    cx, cy, r = circle["x"], circle["y"], circle["radius"]
    pad = int(r * _CROP_PADDING_MULTIPLIER)
    x0  = max(0, cx - pad)
    y0  = max(0, cy - pad)
    x1  = min(img_w, cx + pad)
    y1  = min(img_h, cy + pad)
    crop = image[y0:y1, x0:x1]
    if crop.size == 0:
        return None

    ch, cw = crop.shape[:2]
    scale_up = max(1.0, _CROP_MIN_DIM / min(ch, cw))
    if scale_up > 1.0:
        crop = cv2.resize(crop, (int(cw * scale_up), int(ch * scale_up)),
                          interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    variants = _build_variants(gray)

    votes: dict[str, list[float]] = {}

    for name, variant_img in variants:
        # PaddleOCR needs a 3-channel image
        if len(variant_img.shape) == 2:
            variant_img = cv2.cvtColor(variant_img, cv2.COLOR_GRAY2BGR)
        ocr_result = engine.ocr(variant_img, cls=OCR_USE_ANGLE_CLS)
        if not ocr_result or not ocr_result[0]:
            continue

        for line in ocr_result[0]:
            text  = _clean(line[1][0])
            score = line[1][1]
            if not _DIGIT_RE.match(text) or score < _MIN_CONFIDENCE:
                continue
            norm = text.lstrip("0") or "0"
            if norm not in recovery_targets:
                continue
            votes.setdefault(norm, []).append(score)
            logger.debug(
                "  Strategy D circle#%d [%s]: '%s' conf=%.3f", idx, name, norm, score
            )

    if not votes:
        return None

    # Pick the digit with the most variant votes; break ties by mean confidence.
    best_num   = max(votes, key=lambda n: (len(votes[n]), sum(votes[n]) / len(votes[n])))
    best_votes = votes[best_num]
    if len(best_votes) < _MIN_VARIANT_VOTES:
        return None

    best_conf = round(sum(best_votes) / len(best_votes), 3)
    return {
        "x": cx, "y": cy, "radius": r,
        "number": best_num,
        "extraction_method": "paddleocr_enhanced",
        "score": best_conf,
        "_votes": len(best_votes),
    }


def _build_variants(gray: np.ndarray) -> list[tuple[str, np.ndarray]]:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    eq    = clahe.apply(gray)

    _, otsu     = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, otsu_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    adaptive_inv = cv2.bitwise_not(adaptive)

    clahe_adaptive = cv2.adaptiveThreshold(
        eq, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )

    return [
        ("gray",          gray),
        ("clahe",         eq),
        ("adaptive",      adaptive),
        ("otsu",          otsu),
        ("otsu_inv",      otsu_inv),
        ("clahe_adaptive", clahe_adaptive),
        ("adaptive_inv",  adaptive_inv),
    ]


def _clean(text: str) -> str:
    return re.sub(r"^\D+|\D+$", "", text.strip())


_ocr_engine = None

def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        logger.info("Strategy D: initialising PaddleOCR engine")
        from paddleocr import PaddleOCR
        _ocr_engine = PaddleOCR(
            use_angle_cls=OCR_USE_ANGLE_CLS,
            lang="en",
            det_limit_side_len=3600,
            det_db_thresh=0.2,
        )
    return _ocr_engine
