const API_ORIGIN = import.meta.env.VITE_API_URL || '';
const BASE = `${API_ORIGIN}/api`;

export async function uploadPdf(file, signal) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/upload`, { method: 'POST', body: form, signal });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Upload failed: ${res.status}`);
  }
  return res.json(); // { jobId, status }
}

export function streamJobStatusUrl(jobId) {
  return `${BASE}/jobs/${jobId}/stream`;
}

export async function getResult(jobId) {
  const res = await fetch(`${BASE}/results/${jobId}`);
  if (!res.ok) throw new Error(`Result fetch failed: ${res.status}`);
  return res.json();
}
