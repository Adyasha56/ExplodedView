export default function ErrorBanner({ message, onRetry }) {
  return (
    <div className="w-full max-w-md mx-auto mt-6">
      <div className="border border-red-200 bg-red-50 rounded px-4 py-3 text-sm text-red-700">
        <p className="font-medium mb-1">Something went wrong</p>
        <p className="text-red-600">{message}</p>
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
