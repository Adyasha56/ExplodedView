"""
Central configuration for the AI worker pipeline.

All tunable constants live here. No module should hardcode a threshold,
path, or magic number — import from this file instead.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────

_STORAGE_ENV = os.getenv("STORAGE_PATH", "../storage")
STORAGE_ROOT = (Path(__file__).parent / _STORAGE_ENV).resolve()
UPLOADS_DIR  = STORAGE_ROOT / "uploads"
OUTPUTS_DIR  = STORAGE_ROOT / "outputs"


def get_job_dir(job_id: str) -> Path:
    d = OUTPUTS_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_artifact_paths(job_id: str) -> dict:
    """
    Return a dict of all artifact file paths for a job.

    Every pipeline module writes its output to one of these paths.
    Using this central registry prevents path strings from being
    scattered across modules.

    Structure on disk:
        storage/outputs/<jobId>/
            pages/
                page_0.png          ← all rendered PDF pages
                page_1.png
            preprocessed.png        ← after grayscale / blur / threshold
            contours.png            ← detected contours drawn on diagram (debug)
            circles.png             ← accepted circles drawn on diagram (debug)
            ocr_results.json        ← raw PaddleOCR output per circle crop
            bom_raw.json            ← BOM rows before normalization
            mappings_debug.json     ← all match attempts (exact + fuzzy)
            diagram.png             ← final diagram image served to frontend
            result.json             ← complete pipeline output
    """
    job_dir = get_job_dir(job_id)
    pages_dir = job_dir / "pages"
    pages_dir.mkdir(exist_ok=True)

    return {
        "job_dir":          job_dir,
        "pages_dir":        pages_dir,
        "diagram":          job_dir / "diagram.png",
        "preprocessed":     job_dir / "preprocessed.png",
        "contours":         job_dir / "contours.png",
        "circles":          job_dir / "circles.png",
        "ocr_results":      job_dir / "ocr_results.json",
        "bom_raw":          job_dir / "bom_raw.json",
        "mappings_debug":   job_dir / "mappings_debug.json",
        "result":           job_dir / "result.json",
    }


# ── Debug ─────────────────────────────────────────────────────────────────────

# Writes intermediate artifacts to the job output dir. Keep false in production.
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# ── PDF Rendering ─────────────────────────────────────────────────────────────

PDF_RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "300"))

# ── Page Classification ───────────────────────────────────────────────────────

PAGE_CLASSIFIER_MIN_TABLE_CELLS = 4

# ── Image Preprocessing ───────────────────────────────────────────────────────

PREPROCESS_BLUR_KERNEL = (3, 3)  # must be odd
PREPROCESS_CLAHE_CLIP_LIMIT = 2.0
PREPROCESS_CLAHE_TILE_SIZE  = (8, 8)
PREPROCESS_MORPH_KERNEL = (3, 3)  # fills gaps in circle boundaries
PREPROCESS_DESKEW_THRESHOLD_DEG = 0.5

# ── Circle Detection ──────────────────────────────────────────────────────────

# Circularity = 4π·area / perimeter². Range 0–1; 1.0 = perfect circle.
CIRCLE_CIRCULARITY_THRESHOLD = float(os.getenv("CIRCLE_CIRCULARITY_THRESHOLD", "0.75"))

CIRCLE_MIN_RADIUS_PX = int(os.getenv("CIRCLE_MIN_RADIUS_PX", "12"))
CIRCLE_MAX_RADIUS_PX = int(os.getenv("CIRCLE_MAX_RADIUS_PX", "80"))
CIRCLE_CROP_PADDING_PX = 4
CIRCLE_CROP_MIN_SIZE_PX = 64  # smaller crops degrade PaddleOCR digit accuracy

# ── OCR ───────────────────────────────────────────────────────────────────────

OCR_LANGUAGE      = os.getenv("OCR_LANGUAGE", "en")
OCR_USE_ANGLE_CLS = False  # callout numbers are always upright
OCR_DIGIT_WHITELIST = set("0123456789")

# ── Mapping Engine ────────────────────────────────────────────────────────────

MAPPING_MAX_EDIT_DISTANCE = int(os.getenv("MAPPING_MAX_EDIT_DISTANCE", "1"))
MAPPING_CONFIDENCE_EXACT = 1.0
MAPPING_CONFIDENCE_FUZZY = 0.7

# ── Gemini LLM ───────────────────────────────────────────────────────────────

GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL        = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "15"))
# Invoked only when deterministic methods leave unresolved items.
LLM_ENABLED = os.getenv("LLM_ENABLED", "false").lower() == "true"
