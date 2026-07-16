import { useEffect, useRef } from 'react';

function BomRow({ row, hotspotNumber, selected, onClick }) {
  const ref = useRef(null);

  useEffect(() => {
    if (selected && ref.current) {
      ref.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [selected]);

  return (
    <li
      ref={ref}
      onClick={onClick}
      className={`
        px-3 py-2.5 rounded-md cursor-pointer transition-colors duration-150 text-sm border
        ${selected
          ? 'bg-purple-50 border-purple-600'
          : 'bg-white border-transparent hover:border-purple-400 hover:bg-purple-50/60'}
      `}
    >
      <div className="flex items-baseline gap-2">
        <span className="text-xs font-mono font-semibold shrink-0 text-purple-600">
          {row.refNo}
        </span>
        <span className="font-medium text-gray-800 truncate">{row.description || '—'}</span>
      </div>
      <div className="flex gap-3 mt-0.5 text-xs text-gray-400">
        {row.partNo && <span>{row.partNo}</span>}
        {row.qty != null && <span>Qty: {row.qty}</span>}
      </div>
    </li>
  );
}

export default function BomPanel({ result, selectedRef, onSelectRef }) {
  if (!result) return null;

  // Build a flat list from mappings (preserving duplicate bom[] entries per hotspot)
  const positioned = result.mappings.flatMap((m) =>
    m.bom.map((row) => ({ ...row, hotspotNumber: m.hotspotNumber }))
  );

  const unpositioned = result.unpositionedBomRows;

  return (
    <div className="h-full flex flex-col border-l border-gray-300 bg-white">
      <div className="px-4 py-4 border-b border-gray-200">
        <h2 className="text-sm font-semibold text-gray-800">Bill of Materials</h2>
        <p className="text-xs text-gray-400 mt-0.5">
          {positioned.length} positioned · {unpositioned.length} unlocated
        </p>
      </div>

      <div className="flex-1 overflow-y-auto">
        <ul className="px-2 py-2 space-y-0.5">
          {positioned.map((row, i) => (
            <BomRow
              key={`${row.refNo}-${i}`}
              row={row}
              hotspotNumber={row.hotspotNumber}
              selected={selectedRef === row.hotspotNumber}
              onClick={() => onSelectRef(
                selectedRef === row.hotspotNumber ? null : row.hotspotNumber
              )}
            />
          ))}
        </ul>

        {unpositioned.length > 0 && (
          <>
            <div className="px-4 py-2 mt-2 border-t border-gray-100">
              <p className="text-xs font-medium text-gray-400 uppercase tracking-wide">
                Not detected on diagram
              </p>
            </div>
            <ul className="px-2 py-1 space-y-0.5">
              {unpositioned.map((row, i) => (
                <li key={`unpos-${row.refNo}-${i}`} className="px-3 py-2.5 text-sm text-gray-400">
                  <div className="flex items-start gap-2">
                    <span className="text-xs font-mono font-semibold shrink-0">{row.refNo}</span>
                    <span className="min-w-0 flex-1 truncate">{row.description || '—'}</span>
                    <span className="shrink-0 whitespace-nowrap rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] font-medium leading-4 text-gray-500">No position</span>
                  </div>
                  {row.partNo && (
                    <p className="text-xs mt-0.5 ml-6">{row.partNo}</p>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
