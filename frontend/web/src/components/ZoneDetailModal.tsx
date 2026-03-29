import { TIER_DEFS } from '../types/NeoState';
import type { NeoState, TierKey } from '../types/NeoState';
import { tierAvgPwm, pwmToOpacity } from '../utils/pwm';

interface Props {
  tierKey: TierKey;
  state: NeoState;
  onClose: () => void;
}

const PENALTY_INFO: Record<TierKey, string> = {
  T1: 'tier1_dim: −1000 pts per 1% reduction (non-negotiable)',
  T2: 'tier2_per10: −50 pts per 10% dim below full',
  T3: 'tier3_outrage: −20 pts per 10% mismatch vs demand',
  T4: 'tier4_per10: −5 pts per 10% dim; +10 pts/s when ON',
};

const TIER_DESCRIPTIONS: Record<TierKey, string> = {
  T1: 'Hospitals — always 255. Critical life-safety infrastructure.',
  T2: 'Utilities — high priority. Scaled by temperature demand factor.',
  T3: 'Residential — match potentiometer demand (duck curve applies).',
  T4: 'Commercial — lowest priority, dimmed first. Revenue when ON.',
};

export function ZoneDetailModal({ tierKey, state, onClose }: Props) {
  const tier = TIER_DEFS.find(t => t.key === tierKey)!;
  const avgPwm = tierAvgPwm(state.pwm, tierKey);
  const avgPct = Math.round(avgPwm / 255 * 100);
  const potAvg = ((state.pot1 + state.pot2) / 2 / 1023);
  const opacity = pwmToOpacity(avgPwm);

  // Per-channel breakdown
  const channels = tier.channels.map(ch => ({
    ch,
    pwm: state.pwm[ch] ?? 0,
    pct: Math.round((state.pwm[ch] ?? 0) / 255 * 100),
  }));

  // Flow metrics
  const flowShare = tier.channels.length / 16;
  const estimatedMa = state.load_ma * flowShare * (avgPwm / 255);

  // Mismatch (T3 only)
  const mismatch = tierKey === 'T3'
    ? Math.abs(avgPwm / 255 - potAvg) * 100
    : null;

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,0.4)',
          zIndex: 40,
        }}
      />

      {/* Panel */}
      <div
        className="animate-fade-in"
        style={{
          position: 'fixed',
          bottom: 24, right: 316,
          width: 300,
          background: 'var(--bg-card)',
          border: `1px solid ${tier.color}60`,
          borderRadius: 12,
          zIndex: 50,
          overflow: 'hidden',
          boxShadow: `0 8px 32px rgba(0,0,0,0.6), 0 0 0 1px ${tier.color}20`,
        }}
      >
        {/* Header */}
        <div style={{
          background: `${tier.color}18`,
          borderBottom: `1px solid ${tier.color}30`,
          padding: '10px 14px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: tier.color }}>
              {tier.key} — {tier.label}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 2 }}>
              {TIER_DESCRIPTIONS[tierKey]}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: 'var(--text-secondary)', fontSize: 16, lineHeight: 1, padding: '2px 6px',
            }}
          >×</button>
        </div>

        {/* Body */}
        <div style={{ padding: '12px 14px', fontSize: 11 }}>
          {/* Brightness bar */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ color: 'var(--text-secondary)' }}>Average brightness</span>
              <span className="mono" style={{ color: tier.color, fontWeight: 700 }}>{avgPct}% ({Math.round(avgPwm)}/255)</span>
            </div>
            <div style={{ height: 6, background: 'var(--bg-dark)', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{
                height: '100%', width: `${avgPct}%`,
                background: tier.color, borderRadius: 3,
                opacity, transition: 'width 0.3s',
                boxShadow: `0 0 8px ${tier.glow}80`,
              }} />
            </div>
          </div>

          {/* Per-channel grid */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 9, color: 'var(--text-dim)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Per channel
            </div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {channels.map(({ ch, pwm: v, pct }) => (
                <div key={ch} style={{
                  background: 'var(--bg-dark)', borderRadius: 4, padding: '4px 7px',
                  border: `1px solid ${tier.color}30`, textAlign: 'center',
                }}>
                  <div style={{ fontSize: 8, color: 'var(--text-dim)', marginBottom: 1 }}>CH{ch}</div>
                  <div className="mono" style={{ fontSize: 10, color: tier.color, opacity: pwmToOpacity(v) }}>{pct}%</div>
                </div>
              ))}
            </div>
          </div>

          {/* Flow estimate */}
          <Row label="Est. current draw" value={`~${Math.round(estimatedMa)} mA`} />

          {/* T3 mismatch */}
          {mismatch !== null && (
            <Row
              label="Demand mismatch"
              value={`${mismatch.toFixed(1)}%`}
              valueColor={mismatch > 20 ? 'var(--red)' : mismatch > 10 ? 'var(--yellow)' : 'var(--green)'}
            />
          )}
          {tierKey === 'T3' && (
            <Row label="Pot demand" value={`${Math.round(potAvg * 100)}%`} />
          )}

          {/* Penalty info */}
          <div style={{
            marginTop: 8, fontSize: 9, color: 'var(--text-secondary)',
            background: 'var(--bg-dark)', borderRadius: 4, padding: '5px 8px',
            border: '1px solid var(--border)',
            fontFamily: 'monospace',
          }}>
            {PENALTY_INFO[tierKey]}
          </div>
        </div>
      </div>
    </>
  );
}

function Row({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
      <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
      <span className="mono" style={{ color: valueColor ?? 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}
