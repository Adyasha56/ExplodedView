import { useState } from 'react';
import { staticUrl } from '../../api/static';
import DropZone from '../upload/DropZone';
import UploadBar from '../upload/UploadBar';
import PipelineTracker from '../pipeline/PipelineTracker';
import DiagramCanvas from '../viewer/DiagramCanvas';
import BomPanel from '../viewer/BomPanel';
import ErrorBanner from '../shared/ErrorBanner';
import { useUpload } from '../../hooks/useUpload';
import { useJobPoller } from '../../hooks/useJobPoller';

// Dotted grid background pattern as an inline SVG data URL
const DOTTED_BG = `url("data:image/svg+xml,%3Csvg width='24' height='24' xmlns='http://www.w3.org/2000/svg'%3E%3Ccircle cx='1' cy='1' r='1' fill='%23cbd5e1'/%3E%3C/svg%3E")`;

export default function Workspace() {
  const [file, setFile]                       = useState(null);
  const [jobId, setJobId]                     = useState(null);
  const [selectedAssemblyIndex, setSelectedAssemblyIndex] = useState(0);
  const [selectedRef, setSelectedRef]         = useState(null);

  const { upload, cancel, uploading, error: uploadError } = useUpload();
  const { job, result, error: pollError } = useJobPoller(jobId);

  const error = uploadError || pollError;

  function handleFile(f) {
    if (f.type !== 'application/pdf') {
      alert('Please select a PDF file.');
      return;
    }
    setFile(f);
  }

  function handleUpload() {
    upload(file, (id) => setJobId(id));
  }

  function handleReset() {
    setFile(null);
    setJobId(null);
    setSelectedAssemblyIndex(0);
    setSelectedRef(null);
  }

  function handleSelectAssembly(index) {
    setSelectedAssemblyIndex(index);
    setSelectedRef(null);
  }

  function handleSelectRef(ref) {
    setSelectedRef((prev) => (prev === ref ? null : ref));
  }

  // ── Viewer state ──────────────────────────────────────────────────────────────
  if (result) {
    const assembly = result.assemblies[selectedAssemblyIndex] ?? result.assemblies[0];
    const totalPdfPages = result.totalPdfPages;

    return (
      <div className="h-screen flex flex-col bg-white">

        {/* ── Top bar ── */}
        <header className="flex items-center justify-between px-5 py-3 border-b border-gray-200 shrink-0 bg-white">
          <div>
            <h1 className="text-sm font-semibold text-gray-900">ExplodedView</h1>
            <p className="text-xs text-gray-400 mt-0.5">{job?.filename}</p>
          </div>
          <button
            onClick={handleReset}
            className="text-xs font-medium text-gray-500 hover:text-purple-600 transition-colors"
          >
            New PDF
          </button>
        </header>

        {/* ── Three-column body ── */}
        <div className="flex flex-1 overflow-hidden min-w-0">

          {/* Left: assembly thumbnail navigator */}
          <nav className="w-44 shrink-0 overflow-y-auto border-r border-gray-200 bg-gray-50 py-2">
            {result.assemblies.map((a, i) => {
              const active = i === selectedAssemblyIndex;
              return (
                <button
                  key={a.assemblyIndex}
                  onClick={() => handleSelectAssembly(i)}
                  className="w-full px-2 py-1.5 text-left focus:outline-none"
                >
                  <div className={`rounded-md overflow-hidden border-2 transition-colors ${active ? 'border-purple-600' : 'border-transparent hover:border-gray-300'}`}>
                    <img
                      src={staticUrl(a.diagramImagePath)}
                      alt={`Assembly ${a.assemblyIndex + 1}`}
                      className="w-full aspect-[3/4] object-cover object-top bg-white"
                      draggable={false}
                    />
                    <div className="px-2 py-1.5 bg-white border-t border-gray-100">
                      <p className={`text-xs font-semibold truncate ${active ? 'text-purple-700' : 'text-gray-700'}`}>
                        Assembly {a.assemblyIndex + 1}
                      </p>
                      <p className="text-[10px] text-gray-400 mt-0.5">
                        Page {a.pageMap.diagramPageIndex + 1} / {totalPdfPages}
                      </p>
                    </div>
                  </div>
                </button>
              );
            })}
          </nav>

          {/* Center: diagram viewer */}
          <div className="flex-1 flex flex-col overflow-hidden min-w-0">
            <div className="px-4 py-2 border-b border-gray-200 shrink-0 flex items-center gap-3">
              <span className="text-sm font-semibold text-gray-900">
                Assembly {assembly.assemblyIndex + 1}
              </span>
              <span className="text-xs text-gray-400">
                diagram p.{assembly.pageMap.diagramPageIndex + 1}/{totalPdfPages} · BOM p.{assembly.pageMap.bomPageIndex + 1}/{totalPdfPages}
              </span>
            </div>
            <div className="flex-1 overflow-hidden">
              <DiagramCanvas
                assembly={assembly}
                selectedRef={selectedRef}
                onSelectRef={handleSelectRef}
              />
            </div>
          </div>

          {/* Right: BOM panel */}
          <aside className="w-80 lg:w-96 shrink-0 overflow-y-auto border-l border-gray-200">
            <BomPanel
              assembly={assembly}
              selectedRef={selectedRef}
              onSelectRef={setSelectedRef}
            />
          </aside>
        </div>
      </div>
    );
  }

  // ── Processing state ──────────────────────────────────────────────────────────
  if (jobId && !result) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-white px-4" style={{ backgroundImage: DOTTED_BG }}>
        <div className="bg-white rounded-lg border border-gray-300 shadow-md px-8 py-8 w-full max-w-md">
          <h1 className="text-base font-semibold text-gray-900 mb-1">Analysing PDF</h1>

          {error ? (
            <ErrorBanner message={error} onRetry={handleReset} />
          ) : (
            <PipelineTracker
              pipelineStep={job?.pipelineStep}
              jobStatus={job?.status}
              filename={job?.filename}
            />
          )}
        </div>
      </div>
    );
  }

  // ── Upload state ──────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-white px-4" style={{ backgroundImage: DOTTED_BG }}>
      <div className="w-full max-w-md px-4">
        <div className="mb-8 text-center">
          <h1 className="text-xl font-semibold tracking-tight text-gray-950">ExplodedView</h1>
          <p className="text-sm text-gray-500 mt-1.5">Upload an engineering PDF to begin</p>
        </div>

        {!file ? (
          <DropZone onFile={handleFile} />
        ) : (
          <UploadBar
            file={file}
            uploading={uploading}
            onUpload={handleUpload}
            onClear={handleReset}
          />
        )}

        {error && <ErrorBanner message={error} onRetry={handleReset} />}
      </div>
    </div>
  );
}
