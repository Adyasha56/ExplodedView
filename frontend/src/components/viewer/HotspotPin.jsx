export default function HotspotPin({ mapping, scaleX, scaleY, selected, onClick }) {
  const cx = mapping.x * scaleX;
  const cy = mapping.y * scaleY;
  const r = Math.max(mapping.radius * scaleX, 10);

  return (
    <g
      onClick={(event) => {
        event.stopPropagation();
        onClick(mapping.hotspotNumber);
      }}
      className="cursor-pointer"
      style={{ outline: 'none' }}
    >
      <circle
        cx={cx} cy={cy} r={r + 2}
        fill="transparent"
        // Larger invisible hit target
      />
      <circle
        cx={cx} cy={cy} r={r}
        fill={selected ? '#7C3AED' : 'white'}
        stroke={selected ? '#7C3AED' : '#374151'}
        strokeWidth={selected ? 2.5 : 1.5}
        fillOpacity={selected ? 0.9 : 0.85}
      />
      <text
        x={cx} y={cy}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={Math.max(r * 0.9, 9)}
        fontWeight="600"
        fill={selected ? 'white' : '#111827'}
        style={{ pointerEvents: 'none', userSelect: 'none' }}
      >
        {mapping.hotspotNumber}
      </text>
    </g>
  );
}
