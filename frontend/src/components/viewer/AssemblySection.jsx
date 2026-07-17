import { useState } from 'react';
import DiagramCanvas from './DiagramCanvas';
import BomPanel from './BomPanel';

export default function AssemblySection({ assembly, showHeader, totalPdfPages }) {
  const [selectedRef, setSelectedRef] = useState(null);

  function handleSelectRef(ref) {
    setSelectedRef((prev) => (prev === ref ? null : ref));
  }

  return (
    <div className="flex flex-col">
      {showHeader && (
        <div className="px-4 py-2 bg-gray-50 border-b border-gray-200">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Assembly {assembly.assemblyIndex + 1}
            <span className="ml-2 font-normal normal-case text-gray-400">
              diagram p.{assembly.pageMap.diagramPageIndex + 1}/{totalPdfPages} · BOM p.{assembly.pageMap.bomPageIndex + 1}/{totalPdfPages}
            </span>
          </p>
        </div>
      )}

      <div className="flex min-h-0">
        <div className="flex-1 min-w-0">
          <DiagramCanvas
            assembly={assembly}
            selectedRef={selectedRef}
            onSelectRef={handleSelectRef}
          />
        </div>
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
