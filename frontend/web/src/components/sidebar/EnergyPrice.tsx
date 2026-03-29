import type { NeoState } from '../../types/NeoState';

interface Props { state: NeoState; }

export function EnergyPrice({ state }: Props) {
  const price = state.market_price;
  const color = price > 2.0 ? 'var(--red)' : price > 1.2 ? 'var(--yellow)' : 'var(--green)';
  const label = price > 2.0 ? 'HIGH' : price > 1.2 ? 'MED' : 'LOW';

  return (
    <div className="card" style={{ borderRadius: 0, borderLeft: 'none', borderRight: 'none' }}>
      <div style={{ fontSize: 10, color: 'var(--text-secondary)', fontWeight: 600, marginBottom: 6, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
        Energy Market
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <span className="mono" style={{ fontSize: 26, fontWeight: 800, color, letterSpacing: '-1px', lineHeight: 1 }}>
          ${price.toFixed(2)}
        </span>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ fontSize: 10, color: 'var(--text-secondary)' }}>/kWh</span>
          <span style={{
            fontSize: 9, fontWeight: 700, color, background: `${color}20`,
            border: `1px solid ${color}40`, borderRadius: 4, padding: '1px 5px'
          }}>{label}</span>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
        <span style={{ color: 'var(--text-secondary)' }}>EIA Retail</span>
        <span className="mono" style={{ color: 'var(--text-primary)' }}>${state.eia_retail.toFixed(4)}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
        <span style={{ color: 'var(--text-secondary)' }}>Grid Demand</span>
        <span className="mono" style={{ color: 'var(--blue)' }}>{(state.eia_demand_mw / 1000).toFixed(0)}k MW</span>
      </div>

      <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{
          width: 6, height: 6, borderRadius: '50%',
          background: state.eia_live ? 'var(--green)' : 'var(--yellow)',
          flexShrink: 0,
        }} />
        <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>
          {state.eia_live ? `EIA live · ${Math.round(state.eia_age_s)}s ago` : 'EIA simulated'}
        </span>
      </div>
    </div>
  );
}
