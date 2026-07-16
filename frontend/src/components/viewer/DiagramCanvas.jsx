import { useEffect, useRef, useState } from 'react';
import HotspotPin from './HotspotPin';

function PartDetails({ mapping, scale, imageSize, onClose }) {
  const rows = mapping.bom || [];
  const popupWidth = 272;
  const popupHeight = Math.min(220, 92 + rows.length * 62);
  const x = mapping.x * scale.x;
  const y = mapping.y * scale.y;
  const placeRight = x + 28 + popupWidth <= imageSize.width;
  const left = Math.max(8, Math.min(placeRight ? x + 28 : x - popupWidth - 28, imageSize.width - popupWidth - 8));
  const top = Math.max(8, Math.min(y - 20, imageSize.height - popupHeight - 8));

  return (
    <div
      className="absolute z-10 w-[17rem] max-h-56 overflow-y-auto rounded-lg border border-gray-300 bg-white p-3 shadow-md"
      style={{ left, top }}
      onClick={(event) => event.stopPropagation()}
      role="dialog"
      aria-label={`Parts for reference ${mapping.hotspotNumber}`}
    >
      <div className="flex items-center justify-between gap-3 border-b border-gray-100 pb-2">
        <p className="text-xs font-semibold text-purple-700">Ref {mapping.hotspotNumber}</p>
        <button onClick={onClose} className="text-xs text-gray-400 hover:text-gray-700 transition-colors">Close</button>
      </div>
      <div className="pt-2 space-y-3">
        {rows.map((row, index) => (
          <div key={`${row.refNo}-${row.partNo}-${index}`} className="text-xs">
            <p className="font-semibold leading-5 text-gray-900">{row.description || '—'}</p>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-gray-500">
              {row.partNo && <span>Part no. {row.partNo}</span>}
              {row.qty != null && <span>Qty {row.qty}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function DiagramCanvas({ result, selectedRef, onSelectRef }) {
  const imgRef = useRef(null);
  const [scale, setScale] = useState({ x: 1, y: 1 });

  function updateScale() {
    const img = imgRef.current;
    if (!img || !result) return;
    setScale({
      x: img.clientWidth  / result.imageWidth,
      y: img.clientHeight / result.imageHeight,
    });
  }

  useEffect(() => {
    updateScale();
    window.addEventListener('resize', updateScale);
    return () => window.removeEventListener('resize', updateScale);
  }, [result]);

  if (!result) return null;

  const selectedMapping = result.mappings.find((mapping) => mapping.hotspotNumber === selectedRef);
  const imageSize = {
    width: imgRef.current?.clientWidth || result.imageWidth,
    height: imgRef.current?.clientHeight || result.imageHeight,
  };

  return (
    <div className="relative flex w-full h-full items-start justify-center overflow-auto bg-gray-50 p-5 sm:p-8" onClick={() => onSelectRef(null)}>
      <div className="relative inline-block">
        <img
          ref={imgRef}
          src={result.diagramImagePath}
          alt="Exploded view diagram"
          onLoad={updateScale}
          className="block max-w-full border border-gray-200 bg-white shadow-sm"
          draggable={false}
        />
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none"
          viewBox={`0 0 ${imgRef.current?.clientWidth || result.imageWidth} ${imgRef.current?.clientHeight || result.imageHeight}`}
          style={{ pointerEvents: 'none' }}
        >
          <g style={{ pointerEvents: 'all' }}>
            {result.mappings.map((m) => (
              <HotspotPin
                key={m.hotspotNumber}
                mapping={m}
                scaleX={scale.x}
                scaleY={scale.y}
                selected={selectedRef === m.hotspotNumber}
                onClick={onSelectRef}
              />
            ))}
          </g>
        </svg>
        {selectedMapping && (
          <PartDetails
            mapping={selectedMapping}
            scale={scale}
            imageSize={imageSize}
            onClose={() => onSelectRef(null)}
          />
        )}
      </div>
    </div>
  );
}
