// Ordered pipeline step definitions matching backend PipelineState constants.
// optional: true means the step can be skipped without being an error.

export const PIPELINE_STEPS = [
  { key: 'PAGE_CLASSIFICATION',  label: 'Classifying pages' },
  { key: 'PDF_RENDERING',        label: 'Rendering diagram' },
  { key: 'IMAGE_PREPROCESSING',  label: 'Processing image' },
  { key: 'CIRCLE_DETECTION',     label: 'Detecting geometry' },
  { key: 'CALLOUT_READING',      label: 'Reading callouts' },
  { key: 'BOM_EXTRACTION',       label: 'Extracting bill of materials' },
  { key: 'MAPPING',              label: 'Mapping hotspots to parts' },
  { key: 'LLM_VALIDATION',       label: 'Validating results', optional: true },
  { key: 'RESULT_GENERATION',    label: 'Generating result' },
];

// Returns 'completed' | 'active' | 'skipped' | 'pending' for each step
// given the current pipelineStep key and overall job status.
export function resolveStepStates(currentStep, jobStatus) {
  const currentIdx = PIPELINE_STEPS.findIndex(s => s.key === currentStep);

  return PIPELINE_STEPS.map((step, idx) => {
    if (jobStatus === 'done') return { ...step, state: 'completed' };

    if (idx < currentIdx) {
      // Steps behind the current: check if optional step was jumped over
      if (step.optional) {
        // If the step directly after this optional step is now active or past,
        // the optional step was skipped.
        const nextIdx = idx + 1;
        if (nextIdx <= currentIdx) return { ...step, state: 'skipped' };
      }
      return { ...step, state: 'completed' };
    }

    if (idx === currentIdx) return { ...step, state: 'active' };

    return { ...step, state: 'pending' };
  });
}
