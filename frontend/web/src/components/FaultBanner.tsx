interface Props {
  fault: string;
  tilt: 0 | 1;
}

export function FaultBanner({ fault, tilt }: Props) {
  if (!fault && tilt === 0) return null;

  const isSeismic = tilt === 1;

  return (
    <div
      className="animate-fault"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 18px',
        background: isSeismic ? 'rgba(99, 9, 17, 0.82)' : 'rgba(77, 46, 10, 0.8)',
        borderBottom: `1px solid ${isSeismic ? 'rgba(255, 111, 125, 0.38)' : 'rgba(244, 188, 87, 0.34)'}`,
        color: isSeismic ? '#ffd6dc' : '#ffe2aa',
        fontSize: 12,
        fontWeight: 700,
        letterSpacing: '0.03em',
      }}
    >
      <span>{isSeismic ? 'Seismic alert' : 'Grid alert'}</span>
      <span style={{ color: 'rgba(255,255,255,0.76)', fontWeight: 500 }}>
        {isSeismic ? 'Commercial tier locked down while critical infrastructure remains prioritized.' : fault}
      </span>
    </div>
  );
}
