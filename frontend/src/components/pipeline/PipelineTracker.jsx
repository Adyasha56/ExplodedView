import { FiCheck, FiX, FiMinus, FiCircle } from 'react-icons/fi';
import { resolveStepStates } from '../../utils/pipelineSteps';

function StepIcon({ state }) {
  if (state === 'completed') return <FiCheck className="text-purple-600" />;
  if (state === 'active')    return <FiCircle className="text-purple-600" />;
  if (state === 'skipped')   return <FiMinus className="text-gray-300" />;
  if (state === 'failed')    return <FiX className="text-red-500" />;
  return <FiCircle className="text-gray-200" />;
}

export default function PipelineTracker({ pipelineStep, jobStatus, filename }) {
  const steps = resolveStepStates(pipelineStep, jobStatus);

  return (
    <div className="w-full max-w-md mx-auto mt-6">
      {filename && (
      <p className="text-xs text-gray-500 mb-5 truncate">{filename}</p>
      )}
      <ul className="space-y-3.5">
        {steps.map((step) => (
          <li key={step.key} className="flex items-center gap-3">
            <span className="w-4 flex justify-center shrink-0">
              <StepIcon state={step.state} />
            </span>
            <span className={`text-sm ${
              step.state === 'active'    ? 'text-purple-700 font-semibold' :
              step.state === 'completed' ? 'text-gray-700 font-medium' :
              step.state === 'skipped'   ? 'text-gray-300' :
              step.state === 'failed'    ? 'text-red-500' :
              'text-gray-300'
            }`}>
              {step.label}
              {step.optional && step.state === 'skipped' && (
                <span className="ml-2 text-xs text-gray-300">skipped</span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
