import { useEffect, useRef, useState } from 'react';
import { PIPELINE_STEPS } from '../../utils/pipelineSteps';

const CYCLE_MS = 1500;

// Same nine real stages the app runs on every upload — see pipelineSteps.js.
export default function PipelineDemo() {
  const [activeIndex, setActiveIndex] = useState(0);
  const reducedMotion = useRef(
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );

  useEffect(() => {
    const interval = setInterval(() => {
      setActiveIndex((i) => (i + 1) % PIPELINE_STEPS.length);
    }, reducedMotion.current ? CYCLE_MS * 1.4 : CYCLE_MS);
    return () => clearInterval(interval);
  }, []);

  const activeStep = PIPELINE_STEPS[activeIndex];

  return (
    <div className="pipeline-demo" role="group" aria-label="Live pipeline preview">
      <div className="pipeline-demo__head">
        <span className="pipeline-demo__live-dot" aria-hidden="true" />
        <span className="pipeline-demo__label">Live pipeline</span>
      </div>

      <ol className="pipeline-demo__steps">
        {PIPELINE_STEPS.map((step, i) => {
          const state = i < activeIndex ? 'done' : i === activeIndex ? 'active' : 'pending';
          return (
            <li key={step.key} className={`pipeline-demo__step is-${state}`}>
              <span className="pipeline-demo__dot" aria-hidden="true" />
              <span className="pipeline-demo__step-label">{step.label}</span>
            </li>
          );
        })}
      </ol>

      <p className="pipeline-demo__log" aria-live="polite">
        <span aria-hidden="true">&gt;</span> {activeStep.label.toLowerCase()}…
      </p>
    </div>
  );
}
