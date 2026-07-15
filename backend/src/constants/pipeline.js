/**
 * PipelineState — canonical processing step identifiers.
 *
 * Used by:
 *   - Job.model.js       (pipelineStep field enum)
 *   - python.bridge.js   (maps Python stdout step strings to these values)
 *   - ai-worker/main.py  (emits these exact strings in status JSON)
 *
 * Keep this file in sync with ai-worker/constants/pipeline_state.py.
 * Any new stage added here MUST also be added there, and vice versa.
 */

const PipelineState = Object.freeze({
  UPLOADING:          'UPLOADING',
  PAGE_CLASSIFICATION:'PAGE_CLASSIFICATION',
  PDF_RENDERING:      'PDF_RENDERING',
  IMAGE_PREPROCESSING:'IMAGE_PREPROCESSING',
  CIRCLE_DETECTION:   'CIRCLE_DETECTION',
  CALLOUT_READING:    'CALLOUT_READING',
  BOM_EXTRACTION:     'BOM_EXTRACTION',
  MAPPING:            'MAPPING',
  LLM_VALIDATION:     'LLM_VALIDATION',
  RESULT_GENERATION:  'RESULT_GENERATION',
  COMPLETED:          'COMPLETED',
  FAILED:             'FAILED',
});

module.exports = PipelineState;
