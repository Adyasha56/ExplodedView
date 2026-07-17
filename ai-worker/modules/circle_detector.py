"""
Circle Detector

Detects callout circle geometry in a preprocessed binary image.
Responsible ONLY for geometry — does not read text inside circles.
Text extraction is the responsibility of callout_reader.py.

Strategy:
  cv2.findContours → circularity filtering → cv2.minEnclosingCircle
"""

import math
import time

import cv2
import numpy as np

from config import (
    CIRCLE_CIRCULARITY_THRESHOLD,
    CIRCLE_MAX_RADIUS_PX,
    CIRCLE_MIN_RADIUS_PX,
)
from utils.logger import get_logger

logger = get_logger("circle_detector")


def detect_circles(preprocessed_image: np.ndarray) -> list[dict]:
    """
    Returns list of { x, y, radius } dicts for circles passing all filters.
    Input must be the binary image from image_preprocessor.preprocess().
    """
    t_start = time.perf_counter()
    logger.info("detect_circles: image %dx%d", preprocessed_image.shape[1], preprocessed_image.shape[0])

    contours, _ = cv2.findContours(
        preprocessed_image, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )
    logger.info("  %d raw contours found", len(contours))

    circles = []
    rejected_small = 0
    rejected_large = 0
    rejected_circularity = 0

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 1:
            continue

        perimeter = cv2.arcLength(contour, closed=True)
        if perimeter < 1:
            continue

        # Circularity: 1.0 = perfect circle; lower = elongated or irregular shape.
        # 4π·A / P² cancels scale so small and large circles are treated equally.
        circularity = (4 * math.pi * area) / (perimeter ** 2)

        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        radius = int(round(radius))
        cx = int(round(cx))
        cy = int(round(cy))

        if radius < CIRCLE_MIN_RADIUS_PX:
            rejected_small += 1
            continue
        if radius > CIRCLE_MAX_RADIUS_PX:
            rejected_large += 1
            continue
        if circularity < CIRCLE_CIRCULARITY_THRESHOLD:
            rejected_circularity += 1
            continue

        circles.append({"x": cx, "y": cy, "radius": radius})

    logger.info(
        "  rejected: %d too small, %d too large, %d not circular enough",
        rejected_small, rejected_large, rejected_circularity,
    )

    # Remove near-duplicate detections: if two circles share nearly the same
    # centre (within one radius), keep the one with the larger radius.
    circles = _deduplicate(circles)

    elapsed = (time.perf_counter() - t_start) * 1000
    logger.info(
        "detect_circles complete in %.1f ms — %d circles accepted",
        elapsed, len(circles),
    )

    return circles


def detect_colored_circles(color_image: np.ndarray) -> list[dict]:
    """
    Detect filled-color callout circles (yellow, amber, cream/ivory) directly
    from the BGR color image using HSV connected components.

    Runs as a SEPARATE pass from detect_circles() and is merged with its results
    in main.py. Designed for assemblies where callout circles have a pale or
    vivid colored fill that THRESH_BINARY_INV makes invisible.

    Shape filters (aspect ratio + compactness) reject large non-circular colored
    elements (axle beams, brackets) even if they fall in the hue range.
    """
    t_start = time.perf_counter()
    h_img, w_img = color_image.shape[:2]
    logger.info("detect_colored_circles: image %dx%d", w_img, h_img)

    hsv = cv2.cvtColor(color_image, cv2.COLOR_BGR2HSV)

    # Yellow / amber / cream / ivory fills.
    # H=12–45 (OpenCV 0–180): amber → yellow (avoids pure red and green).
    # S≥20: catches pale cream (S≈25–35) while ignoring grey/white (S<10).
    # V≥140: bright enough to be a callout fill, not a shadow or dark part.
    mask = cv2.inRange(hsv, (12, 20, 140), (45, 255, 255))

    # Close small holes left by dark text/digits printed inside the circle fill.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    logger.info("  %d colored component(s) found", num_labels - 1)

    circles: list[dict] = []
    rej_size = rej_shape = 0

    for i in range(1, num_labels):  # 0 = background
        area = int(stats[i, cv2.CC_STAT_AREA])
        w    = int(stats[i, cv2.CC_STAT_WIDTH])
        h    = int(stats[i, cv2.CC_STAT_HEIGHT])

        # Equivalent radius of a filled circle with the same pixel count.
        eq_r = math.sqrt(area / math.pi)

        if eq_r < CIRCLE_MIN_RADIUS_PX or eq_r > CIRCLE_MAX_RADIUS_PX:
            rej_size += 1
            logger.debug(
                "    comp %d: eq_r=%.1f outside [%d,%d] — size-rejected",
                i, eq_r, CIRCLE_MIN_RADIUS_PX, CIRCLE_MAX_RADIUS_PX,
            )
            continue

        # Shape filters: callout circles have a square bbox and fill ≈ π/4 of it.
        # Large elongated parts (axle beams, straps) have aspect << 1 or
        # compactness far from the circle ideal of 0.785.
        aspect      = min(w, h) / max(w, h) if max(w, h) > 0 else 0
        compactness = area / (w * h)         if w * h > 0     else 0

        if aspect < 0.70 or not (0.50 <= compactness <= 0.95):
            rej_shape += 1
            logger.debug(
                "    comp %d: eq_r=%.1f aspect=%.2f compact=%.2f — shape-rejected",
                i, eq_r, aspect, compactness,
            )
            continue

        cx = int(round(centroids[i][0]))
        cy = int(round(centroids[i][1]))
        radius = max(CIRCLE_MIN_RADIUS_PX, int(round(eq_r)))

        logger.debug(
            "    comp %d: cx=%d cy=%d r=%d (eq_r=%.1f aspect=%.2f compact=%.2f) — accepted",
            i, cx, cy, radius, eq_r, aspect, compactness,
        )
        circles.append({"x": cx, "y": cy, "radius": radius})

    circles = _deduplicate(circles)

    elapsed = (time.perf_counter() - t_start) * 1000
    logger.info(
        "detect_colored_circles complete in %.1f ms — %d size-rej, %d shape-rej, %d accepted",
        elapsed, rej_size, rej_shape, len(circles),
    )
    return circles


def merge_circle_lists(*lists: list[dict]) -> list[dict]:
    """Combine multiple circle detection results and remove near-duplicates."""
    combined: list[dict] = []
    for lst in lists:
        combined.extend(lst)
    return _deduplicate(combined)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _deduplicate(circles: list[dict]) -> list[dict]:
    """
    Remove near-duplicate circle detections.

    Two circles are considered duplicates when their centres are closer
    than the larger circle's radius. The larger circle is kept because
    findContours sometimes detects both the inner and outer boundary of
    the same callout ring.
    """
    if not circles:
        return circles

    # Sort largest-first so we always keep the outer circle on collision
    sorted_circles = sorted(circles, key=lambda c: c["radius"], reverse=True)
    kept = []

    for candidate in sorted_circles:
        duplicate = False
        for accepted in kept:
            dx = candidate["x"] - accepted["x"]
            dy = candidate["y"] - accepted["y"]
            distance = math.sqrt(dx * dx + dy * dy)
            if distance < min(accepted["radius"], candidate["radius"]):
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)

    if len(kept) < len(circles):
        logger.debug("  deduplication removed %d near-duplicate(s)", len(circles) - len(kept))

    return kept
