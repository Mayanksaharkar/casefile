const COLORS = {
  critical: '#b3432b',
  high: '#c97a2a',
  medium: '#8a8547',
  low: '#5b7065',
};

export default function SeverityBadge({ severity }) {
  const color = COLORS[severity] || COLORS.low;
  return (
    <span className="severity-tag" style={{ background: color }}>
      {severity}
    </span>
  );
}

export { COLORS };
