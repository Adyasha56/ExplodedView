"""
Central configuration for the AI worker pipeline.

All tunable constants live here. No module should hardcode a threshold,
path, or magic number — import from this file instead.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths 
_STORAGE_ENV = os.getenv("STORAGE_PATH", "../storage")
STORAGE_ROOT = (Path(__file__).parent / _STORAGE_ENV).resolve()
UPLOADS_DIR  = STORAGE_ROOT / "uploads"
OUTPUTS_DIR  = STORAGE_ROOT / "outputs"


def get_job_dir(job_id: str) -> Path:
    d = OUTPUTS_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_artifact_paths(job_id: str, assembly_index: int = 0) -> dict:
    """
    Return artifact file paths for one assembly within a job.

    Each assembly gets its own subdirectory so multi-assembly PDFs don't
    overwrite each other's diagrams or debug artifacts.

    Structure on disk:
        storage/outputs/<jobId>/
            assembly_0/
                diagram.png         ← rendered diagram page for this assembly
                preprocessed.png    ← after grayscale / blur / threshold (debug)
                contours.png        ← detected contours drawn on diagram (debug)
                circles.png         ← accepted circles drawn on diagram (debug)
                ocr_results.json    ← raw PaddleOCR output per circle crop (debug)
                bom_raw.json        ← BOM rows before normalization (debug)
                mappings_debug.json ← all match attempts (debug)
            assembly_1/
                ...
            result.json             ← complete multi-assembly output (top-level)
    """
    job_dir      = get_job_dir(job_id)
    assembly_dir = job_dir / f"assembly_{assembly_index}"
    assembly_dir.mkdir(parents=True, exist_ok=True)

    return {
        "job_dir":          job_dir,
        "assembly_dir":     assembly_dir,
        "diagram":          assembly_dir / "diagram.png",
        "preprocessed":     assembly_dir / "preprocessed.png",
        "contours":         assembly_dir / "contours.png",
        "circles":          assembly_dir / "circles.png",
        "ocr_results":      assembly_dir / "ocr_results.json",
        "bom_raw":          assembly_dir / "bom_raw.json",
        "mappings_debug":   assembly_dir / "mappings_debug.json",
        "result":           job_dir / "result.json",
    }


# ── Debug 
# Writes intermediate artifacts to the job output dir. Keep false in production.
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# ── PDF Rendering

PDF_RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "300"))

# ── Page Classification
PAGE_CLASSIFIER_MIN_TABLE_CELLS = 4

# ── Image Preprocessing
PREPROCESS_BLUR_KERNEL = (3, 3)  # must be odd
PREPROCESS_CLAHE_CLIP_LIMIT = 2.0
PREPROCESS_CLAHE_TILE_SIZE  = (8, 8)
PREPROCESS_MORPH_KERNEL = (3, 3)  # fills gaps in circle boundaries
PREPROCESS_DESKEW_THRESHOLD_DEG = 0.5

# ── Circle Detection 

# Circularity = 4π·area / perimeter². Range 0–1; 1.0 = perfect circle.
CIRCLE_CIRCULARITY_THRESHOLD = float(os.getenv("CIRCLE_CIRCULARITY_THRESHOLD", "0.75"))

CIRCLE_MIN_RADIUS_PX = int(os.getenv("CIRCLE_MIN_RADIUS_PX", "12"))
CIRCLE_MAX_RADIUS_PX = int(os.getenv("CIRCLE_MAX_RADIUS_PX", "120"))
CIRCLE_CROP_PADDING_PX = 4
CIRCLE_CROP_MIN_SIZE_PX = 64  # smaller crops degrade PaddleOCR digit accuracy

# ── OCR 
OCR_LANGUAGE      = os.getenv("OCR_LANGUAGE", "en")
OCR_USE_ANGLE_CLS = False  # callout numbers are always upright
OCR_DIGIT_WHITELIST = set("0123456789")

# ── Mapping Engine 

MAPPING_MAX_EDIT_DISTANCE = int(os.getenv("MAPPING_MAX_EDIT_DISTANCE", "1"))
MAPPING_CONFIDENCE_EXACT = 1.0
MAPPING_CONFIDENCE_FUZZY = 0.7

# ── Gemini LLM 

GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL        = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "15"))
# Invoked only when deterministic methods leave unresolved items.
LLM_ENABLED = os.getenv("LLM_ENABLED", "false").lower() == "true"
