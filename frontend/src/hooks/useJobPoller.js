import { useEffect, useState } from 'react';
import { streamJobStatusUrl, getResult } from '../api/pipeline';

export function useJobPoller(jobId) {
  const [job, setJob] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setJob(null);
    setResult(null);
    setError(null);
    if (!jobId) return;
    let cancelled = false;

    const source = new EventSource(streamJobStatusUrl(jobId));

    source.onmessage = async (event) => {
      if (cancelled) return;
      const data = JSON.parse(event.data);
      setJob(data);

      if (data.status === 'error') {
        setError(data.errorMessage || 'Pipeline failed.');
        source.close();
        return;
      }

      if (data.status === 'done') {
        source.close();
        try {
          const res = await getResult(jobId);
          if (!cancelled) setResult(res);
        } catch (err) {
          if (!cancelled) setError(err.message);
        }
      }
    };

    source.onerror = () => {
      if (cancelled) return;
      setError('Lost connection to job status stream.');
      source.close();
    };

    return () => {
      cancelled = true;
      source.close();
    };
  }, [jobId]);

  return { job, result, error };
}
