import { useRef, useState } from 'react';
import { FiUploadCloud } from 'react-icons/fi';

export default function DropZone({ onFile }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);

  function handleDrop(e) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) onFile(file);
  }

  function handleChange(e) {
    const file = e.target.files?.[0];
    if (file) onFile(file);
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      className={`
        w-full max-w-md mx-auto cursor-pointer rounded-lg border-2 border-dashed bg-white px-10 py-16
        flex flex-col items-center gap-3 select-none transition-colors duration-150
        ${dragging ? 'border-purple-600 bg-purple-50' : 'border-gray-400 hover:border-purple-600 hover:bg-purple-50/50'}
      `}
    >
      <FiUploadCloud className={`text-4xl ${dragging ? 'text-purple-600' : 'text-gray-600'}`} />
      <p className="text-sm font-semibold text-gray-800">Drop a PDF here</p>
      <p className="text-xs text-gray-500">or click to browse</p>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={handleChange}
      />
    </div>
  );
}
