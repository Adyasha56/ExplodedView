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
            if distance < accepted["radius"]:
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)

    if len(kept) < len(circles):
        logger.debug("  deduplication removed %d near-duplicate(s)", len(circles) - len(kept))

    return kept
