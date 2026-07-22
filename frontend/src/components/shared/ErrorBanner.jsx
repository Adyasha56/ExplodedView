import { FiX } from 'react-icons/fi';

export default function ErrorBanner({ message, onRetry, onDismiss }) {
  return (
    <div className="w-full max-w-md mx-auto mt-6">
      <div className="border border-red-200 bg-red-50 rounded px-4 py-3 text-sm text-red-600 flex items-start justify-between gap-2">
        <span>{message}</span>
        {onDismiss && (
          <button onClick={onDismiss} className="shrink-0 text-red-400 hover:text-red-600 transition-colors">
            <FiX size={14} />
          </button>
        )}
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 w-full py-2 text-sm font-medium border border-black rounded hover:bg-black hover:text-white transition-colors"
        >
          Try again
        </button>
      )}
    </div>
  );
}
