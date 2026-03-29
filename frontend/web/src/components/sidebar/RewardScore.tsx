import type { NeoState } from '../../types/NeoState';

interface Props { state: NeoState; }

export function RewardScore({ state }: Props) {
  const score = state.reward_score;

  const isPositive = score >= 0;
  const color = isPositive ? 'var(--green)' : 'var(--red)';

  return (
    <div className="card" style={{ borderRadius: 0, borderLeft: 'none', borderRight: 'none' }}>
      <div style={{ fontSize: 10, color: 'var(--text-secondary)', fontWeight: 600, marginBottom: 6, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
        AI Score
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
        <span className="mono" style={{ fontSize: 24, fontWeight: 800, color, letterSpacing: '-1px', lineHeight: 1 }}>
          {score >= 0 ? '+' : ''}{Math.round(score).toLocaleString()}
        </span>
        <span style={{ fontSize: 10, color: 'var(--text-secondary)' }}>pts</span>
        <span style={{ fontSize: 10, color: 'var(--text-dim)', marginLeft: 'auto' }}>K2 calls: {state.k2_calls}</span>
      </div>
      <div style={{
        marginTop: 8,
        display: 'grid',
        gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
        gap: 8,
      }}>
        <MetricCard label="Loop" value={`${state.loop_ms.toFixed(0)} ms`} />
        <MetricCard label="Optimizer" value={state.active_policy || 'None'} />
        <MetricCard label="Deficit" value={`${Math.round(state.ttd_seconds)} s`} />
        <MetricCard label="Forecast" value={`${Math.round(state.storm_probability * 100)}%`} />
      </div>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      padding: '8px 10px',
      borderRadius: 10,
      background: 'rgba(8, 14, 20, 0.9)',
      border: '1px solid rgba(181, 199, 216, 0.08)',
    }}>
      <div style={{ color: 'var(--text-dim)', fontSize: 9, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        {label}
      </div>
      <div className="mono" style={{ color: 'var(--text-primary)', fontSize: 11 }}>
        {value}
      </div>
    </div>
  );
}
