"""
Image Preprocessor

Prepares a raw diagram PNG for contour-based circle detection.
Must be run before circle_detector.py.

Pipeline (in order):
  1. Grayscale conversion
  2. Gaussian blur          — suppresses rendering artifacts
  3. CLAHE                  — normalises contrast across diagram regions
  4. Otsu's thresholding    — produces binary image for contour detection
  5. Morphological closing  — fills gaps in circle boundaries
  6. Deskew (optional)      — corrects rotation if skew > threshold
"""

import time

import cv2
import numpy as np

from config import (
    PREPROCESS_BLUR_KERNEL,
    PREPROCESS_CLAHE_CLIP_LIMIT,
    PREPROCESS_CLAHE_TILE_SIZE,
    PREPROCESS_DESKEW_THRESHOLD_DEG,
    PREPROCESS_MORPH_KERNEL,
)
from utils.logger import get_logger

logger = get_logger("image_preprocessor")


def preprocess(image: np.ndarray, debug: bool = False) -> np.ndarray:
    """Return a binary image ready for cv2.findContours."""
    t_start = time.perf_counter()
    h, w = image.shape[:2]
    logger.info("preprocess: input image %d×%d px", w, h)

    if image.ndim == 3:
        # Suppress vivid yellow/orange fills before grayscale so they survive
        # THRESH_BINARY_INV. Low-saturation cream fills are handled by the
        # separate detect_colored_circles() pass in main.py instead — masking
        # them here at S<60 catches large coloured parts (axle bodies, brackets)
        # which create irregular blobs that corrupt circle detection.
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        # S≥60 keeps only vivid yellow/orange; pale cream (S≈25-35) is skipped
        # intentionally and handled by the HSV connected-component pass.
        yellow_mask = cv2.inRange(hsv, (12, 60, 80), (45, 255, 255))
        image_work = image.copy()
        image_work[yellow_mask > 0] = (30, 30, 30)
        gray = cv2.cvtColor(image_work, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    if debug:
        logger.debug("  step 1 grayscale: %s", gray.shape)

    blurred = cv2.GaussianBlur(gray, PREPROCESS_BLUR_KERNEL, 0)

    if debug:
        logger.debug("  step 2 blur: kernel=%s", PREPROCESS_BLUR_KERNEL)

    # CLAHE normalises local contrast so faint circle edges in low-contrast
    # regions are as detectable as high-contrast ones (critical for scanned drawings).
    clahe = cv2.createCLAHE(
        clipLimit=PREPROCESS_CLAHE_CLIP_LIMIT,
        tileGridSize=PREPROCESS_CLAHE_TILE_SIZE,
    )
    enhanced = clahe.apply(blurred)

    if debug:
        logger.debug(
            "  step 3 CLAHE: clipLimit=%.1f tileGrid=%s",
            PREPROCESS_CLAHE_CLIP_LIMIT,
            PREPROCESS_CLAHE_TILE_SIZE,
        )

    # THRESH_BINARY_INV: edges become white on black, which findContours expects.
    _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    otsu_thresh = _get_otsu_value(enhanced)

    if debug:
        logger.debug("  step 4 Otsu threshold: T=%.0f", otsu_thresh)

    # Closing bridges gaps in circle perimeters from anti-aliasing/low-contrast.
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, PREPROCESS_MORPH_KERNEL
    )
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    if debug:
        logger.debug("  step 5 morphological close: kernel=%s", PREPROCESS_MORPH_KERNEL)

    result, skew_angle = _deskew(closed, PREPROCESS_DESKEW_THRESHOLD_DEG)

    if abs(skew_angle) >= PREPROCESS_DESKEW_THRESHOLD_DEG:
        logger.info("  step 6 deskew: corrected %.2f°", skew_angle)
    else:
        logger.debug("  step 6 deskew: skew %.2f° below threshold, skipped", skew_angle)

    elapsed = (time.perf_counter() - t_start) * 1000
    logger.info("preprocess complete in %.1f ms", elapsed)

    return result


# ── Internal helpers ───────────────────────────────────────────────────────────

def _get_otsu_value(gray: np.ndarray) -> float:
    thresh, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh


def _deskew(binary: np.ndarray, threshold_deg: float) -> tuple[np.ndarray, float]:
    """
    Detect and correct image skew using the dominant angle of non-zero pixels.
    Returns the (possibly rotated) image and the detected angle in degrees.

    OpenCV 4.5+ changed minAreaRect to return angles in (-90°, 90°] instead of
    [-90°, 0°). We cap at ±10° — larger values are detection artifacts from
    content spread across the full page, not actual skew.
    """
    _MAX_SKEW_DEG = 10.0

    non_zero = np.column_stack(np.where(binary > 0))  # (row, col) pairs

    if len(non_zero) < 50:
        return binary, 0.0

    points = non_zero[:, ::-1].astype(np.float32)  # (row, col) -> (x, y)
    _, _, angle = cv2.minAreaRect(points)

    # Angles near ±90° mean the dominant content direction is vertical — not actual
    # 90° skew. Map to the equivalent small angle.
    if angle > 45:
        angle -= 90
    elif angle < -45:
        angle += 90

    # If angle still exceeds the cap, minAreaRect found no reliable dominant
    # direction (common for diagrams with lines in all directions).
    if abs(angle) > _MAX_SKEW_DEG:
        return binary, 0.0

    if abs(angle) < threshold_deg:
        return binary, angle

    (h, w) = binary.shape
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        binary, M, (w, h),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return rotated, angle
