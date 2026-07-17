import { useEffect, useRef, useState } from 'react';
import { getJobStatus, getResult } from '../api/pipeline';

const POLL_INTERVAL_MS = 2000;
const TERMINAL = new Set(['done', 'error']);

export function useJobPoller(jobId) {
  const [job, setJob] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => {
    setJob(null);
    setResult(null);
    setError(null);
    if (!jobId) return;
    let cancelled = false;

    async function poll() {
      try {
        const data = await getJobStatus(jobId);
        if (cancelled) return;
        setJob(data);

        if (data.status === 'error') {
          setError(data.errorMessage || 'Pipeline failed.');
          return;
        }

        if (data.status === 'done') {
          const res = await getResult(jobId);
          if (!cancelled) setResult(res);
          return;
        }

        timerRef.current = setTimeout(poll, POLL_INTERVAL_MS);
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    }

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timerRef.current);
    };
  }, [jobId]);

  return { job, result, error };
}
