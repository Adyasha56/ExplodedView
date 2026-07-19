import { FiFile, FiX } from 'react-icons/fi';

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function UploadBar({ file, uploading, onUpload, onClear }) {
  return (
    <div className="w-full max-w-md mx-auto mt-4 border border-gray-200 rounded px-4 py-3">
      <div className="flex items-center gap-3">
        <FiFile className="text-gray-500 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-800 truncate">{file.name}</p>
          <p className="text-xs text-gray-400">{formatSize(file.size)}</p>
        </div>
        {!uploading && (
          <button onClick={onClear} className="text-gray-400 hover:text-gray-600">
            <FiX />
          </button>
        )}
      </div>

      {uploading ? (
        <div className="mt-3 flex items-center gap-2">
          <div className="h-1 flex-1 bg-gray-100 rounded overflow-hidden">
            <div className="h-full bg-purple-600 animate-pulse w-2/3" />
          </div>
          <span className="text-xs text-gray-400 shrink-0">Analysing PDF…</span>
        </div>
      ) : (
        <button
          onClick={onUpload}
          className="mt-3 w-full py-2 text-sm font-medium bg-purple-600 text-white rounded hover:bg-purple-700 transition-colors"
        >
          Analyse PDF
        </button>
      )}
    </div>
  );
}
