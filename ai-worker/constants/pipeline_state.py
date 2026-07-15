"""
PipelineState — canonical processing step identifiers for the Python worker.

Must stay in sync with backend/src/constants/pipeline.js.
The strings emitted in main.py status JSON must match the keys in
python.bridge.js STEP_MAP exactly (lowercase_underscore form).
"""

from enum import Enum


class PipelineState(str, Enum):
    """
    Using str+Enum so values serialise directly to JSON strings
    without needing .value — e.g. json.dumps({"step": PipelineState.MAPPING})
    produces {"step": "mapping"} automatically.
    """
    UPLOADING           = "UPLOADING"
    PAGE_CLASSIFICATION = "PAGE_CLASSIFICATION"
    PDF_RENDERING       = "PDF_RENDERING"
    IMAGE_PREPROCESSING = "IMAGE_PREPROCESSING"
    CIRCLE_DETECTION    = "CIRCLE_DETECTION"
    CALLOUT_READING     = "CALLOUT_READING"
    BOM_EXTRACTION      = "BOM_EXTRACTION"
    MAPPING             = "MAPPING"
    LLM_VALIDATION      = "LLM_VALIDATION"
    RESULT_GENERATION   = "RESULT_GENERATION"
    COMPLETED           = "COMPLETED"
    FAILED              = "FAILED"


# Step strings emitted to stdout for Node.js bridge consumption.
# These lowercase_underscore values are the keys in python.bridge.js STEP_MAP.
STEP_LABELS = {
    PipelineState.PAGE_CLASSIFICATION: "page_classification",
    PipelineState.PDF_RENDERING:       "pdf_rendering",
    PipelineState.IMAGE_PREPROCESSING: "image_preprocessing",
    PipelineState.CIRCLE_DETECTION:    "circle_detection",
    PipelineState.CALLOUT_READING:     "callout_reading",
    PipelineState.BOM_EXTRACTION:      "bom_extraction",
    PipelineState.MAPPING:             "mapping",
    PipelineState.LLM_VALIDATION:      "llm_validation",
    PipelineState.RESULT_GENERATION:   "result_writing",
}
