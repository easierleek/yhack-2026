import type { NeoState } from '../../types/NeoState';

interface Props { state: NeoState; }

function arcPath(cx: number, cy: number, r: number, startDeg: number, endDeg: number) {
  const toRad = (d: number) => (d - 90) * Math.PI / 180;
  const x1 = cx + r * Math.cos(toRad(startDeg));
  const y1 = cy + r * Math.sin(toRad(startDeg));
  const x2 = cx + r * Math.cos(toRad(endDeg));
  const y2 = cy + r * Math.sin(toRad(endDeg));
  const large = endDeg - startDeg > 180 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
}

export function SocGauge({ state }: Props) {
  const soc = state.battery_soc;
  const pct = Math.round(soc * 100);
  const startDeg = -135;
  const totalSweep = 270;
  const fillDeg = startDeg + totalSweep * soc;

  const color = soc > 0.55 ? '#5bffa0' : soc > 0.25 ? '#FFD740' : '#FF5566';

  const cx = 60, cy = 58, r = 40;

  return (
    <div className="card" style={{ borderRadius: 0, borderLeft: 'none', borderRight: 'none', borderTop: 'none' }}>
      <div style={{ fontSize: 10, color: 'var(--text-secondary)', fontWeight: 600, marginBottom: 8, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
        Solar Battery
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {/* Gauge */}
        <svg width="120" height="80" viewBox="0 0 120 80">
          {/* Background track */}
          <path
            d={arcPath(cx, cy, r, startDeg, startDeg + totalSweep)}
            fill="none" stroke="#243347" strokeWidth="8" strokeLinecap="round"
          />
          {/* Fill arc */}
          <path
            d={arcPath(cx, cy, r, startDeg, fillDeg)}
            fill="none" stroke={color} strokeWidth="8" strokeLinecap="round"
            style={{ transition: 'all 0.4s ease', filter: `drop-shadow(0 0 4px ${color}66)` }}
          />
          {/* Duck demand overlay (thin arc) */}
          {(() => {
            const duckDeg = startDeg + totalSweep * state.duck_demand;
            return (
              <path
                d={arcPath(cx, cy, r - 12, startDeg, duckDeg)}
                fill="none" stroke="#7FC8FF" strokeWidth="3" strokeLinecap="round" opacity="0.5"
              />
            );
          })()}
          {/* Center text */}
          <text x={cx} y={cy - 6} textAnchor="middle" fontSize="18" fontWeight="800" fill={color} fontFamily="monospace">
            {pct}%
          </text>
          <text x={cx} y={cy + 10} textAnchor="middle" fontSize="8" fill="var(--text-secondary)">
            SoC
          </text>
        </svg>

        {/* Stats */}
        <div style={{ flex: 1, fontSize: 11 }}>
          <StatRow label="Solar" value={`${Math.round(state.solar_ma)} mA`} />
          <StatRow label="Load"  value={`${Math.round(state.load_ma)} mA`} />
          <StatRow
            label="Net"
            value={`${state.solar_ma - state.load_ma >= 0 ? '+' : ''}${Math.round(state.solar_ma - state.load_ma)} mA`}
            valueColor={state.solar_ma >= state.load_ma ? 'var(--green)' : 'var(--red)'}
          />
          <StatRow
            label="Demand"
            value={`${Math.round(state.duck_demand * 100)}%`}
            valueColor="var(--blue)"
          />
        </div>
      </div>
    </div>
  );
}

function StatRow({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
      <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
      <span className="mono" style={{ color: valueColor ?? 'var(--text-primary)', fontSize: 11 }}>{value}</span>
    </div>
  );
}
