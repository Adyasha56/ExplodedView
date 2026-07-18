const API_ORIGIN = import.meta.env.VITE_API_URL || '';

// In prod, diagramImagePath is a Cloudinary URL (absolute) — return as-is.
// In local dev, it's "/static/outputs/..." — prepend empty string (Vite proxy handles it).
export function staticUrl(path) {
  if (path && path.startsWith('http')) return path;
  return `${API_ORIGIN}${path}`;
}
