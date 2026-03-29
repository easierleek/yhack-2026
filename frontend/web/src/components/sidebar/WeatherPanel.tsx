import type { NeoState } from '../../types/NeoState';

interface Props { state: NeoState; }

function slopeArrow(slope: number) {
  if (slope > 15) return '↑↑';
  if (slope > 3)  return '↑';
  if (slope < -15) return '↓↓';
  if (slope < -3)  return '↓';
  return '→';
}

export function WeatherPanel({ state }: Props) {
  const storm = state.storm_probability;
  const stormColor = storm > 0.6 ? 'var(--red)' : storm > 0.3 ? 'var(--yellow)' : 'var(--green)';
  const lightPct = Math.round(state.light / 1023 * 100);
  const solarRunway = state.solar_time_remaining < 99990 ? `${Math.round(state.solar_time_remaining)}s` : 'Stable';

  return (
    <div className="card" style={{ borderRadius: 0, borderLeft: 'none', borderRight: 'none' }}>
      <div style={{ fontSize: 10, color: 'var(--text-secondary)', fontWeight: 600, marginBottom: 8, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
        Weather / Environment
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 10px', fontSize: 11 }}>
        <StatRow label="Temp" value={`${state.temp_c.toFixed(1)} °C`} valueColor={state.temp_c > 28 ? 'var(--red)' : undefined} />
        <StatRow label="Pressure" value={`${state.pressure_hpa.toFixed(0)} hPa ${slopeArrow(state.pressure_slope * 1000)}`} />
        <StatRow label="Light" value={`${lightPct}% ${slopeArrow(state.sun_slope)}`} valueColor={lightPct > 50 ? 'var(--yellow)' : undefined} />
        <StatRow label="Demand spike" value={state.mins_to_demand_spike < 9990 ? `${Math.round(state.mins_to_demand_spike)}m` : 'None'} />
        <StatRow label="Solar runway" value={solarRunway} valueColor={state.solar_time_remaining < 180 ? 'var(--yellow)' : undefined} />
        <StatRow label="T2 factor" value={`${state.t2_demand_factor.toFixed(2)}x`} valueColor={state.t2_demand_factor > 1.2 ? 'var(--yellow)' : undefined} />
      </div>

      {/* Storm probability bar */}
      <div style={{ marginTop: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, marginBottom: 3 }}>
          <span style={{ color: 'var(--text-secondary)' }}>Storm probability</span>
          <span className="mono" style={{ color: stormColor }}>{Math.round(storm * 100)}%</span>
        </div>
        <div style={{ height: 4, background: 'var(--bg-dark)', borderRadius: 2, overflow: 'hidden' }}>
          <div style={{
            height: '100%',
            width: `${storm * 100}%`,
            background: stormColor,
            borderRadius: 2,
            transition: 'width 0.4s ease, background 0.4s ease',
          }} />
        </div>
      </div>

      {state.market_penalty_active && (
        <div style={{
          marginTop: 8,
          fontSize: 10,
          fontWeight: 700,
          color: 'var(--yellow)',
          background: 'rgba(74, 56, 0, 0.42)',
          border: '1px solid rgba(244, 188, 87, 0.24)',
          borderRadius: 6,
          padding: '5px 8px',
          textAlign: 'center',
        }}>
          High market price is actively penalizing relay use
        </div>
      )}

      {/* Seismic */}
      {state.tilt === 1 && (
        <div style={{
          marginTop: 8, fontSize: 10, fontWeight: 700, color: 'var(--red)',
          background: '#2a0000', border: '1px solid #660000', borderRadius: 4,
          padding: '4px 8px', textAlign: 'center',
        }} className="animate-fault">
          🚨 SEISMIC EVENT DETECTED
        </div>
      )}
    </div>
  );
}

function StatRow({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div>
      <div style={{ color: 'var(--text-dim)', fontSize: 9, marginBottom: 1 }}>{label}</div>
      <div className="mono" style={{ color: valueColor ?? 'var(--text-primary)', fontSize: 11 }}>{value}</div>
    </div>
  );
}
