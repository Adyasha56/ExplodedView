import { useRef, useState } from 'react';
import { uploadPdf } from '../api/pipeline';

export function useUpload() {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  async function upload(file, onSuccess) {
    setUploading(true);
    setError(null);
    abortRef.current = new AbortController();
    try {
      const { jobId } = await uploadPdf(file, abortRef.current.signal);
      onSuccess(jobId);
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message);
    } finally {
      setUploading(false);
    }
  }

  function cancel() {
    abortRef.current?.abort();
  }

  function clearError() {
    setError(null);
  }

  return { upload, cancel, uploading, error, clearError };
}
