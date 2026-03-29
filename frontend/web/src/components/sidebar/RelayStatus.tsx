import type { NeoState } from '../../types/NeoState';
import { fmtTtd } from '../../utils/pwm';

interface Props { state: NeoState; }

const POLICY_LABELS: Record<number, string> = {
  1: 'Industrial Curfew',
  2: 'Solar Subsidy',
  3: 'Brownout Protocol',
  4: 'Emergency Grid',
  5: 'Commercial Lockdown',
};

export function RelayStatus({ state }: Props) {
  const isSolar = state.relay === 0;
  const policyCountdown = state.policy_real_expires && state.policy_real_expires > 0
    ? `${Math.round(state.policy_real_expires)}s real / ${Math.round(state.policy_expires_in ?? 0)}s sim`
    : null;

  return (
    <div className="card" style={{ borderRadius: 0, borderLeft: 'none', borderRight: 'none' }}>
      <div style={{ fontSize: 10, color: 'var(--text-secondary)', fontWeight: 600, marginBottom: 8, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
        Grid Source
      </div>

      {/* Two-state toggle */}
      <div style={{
        display: 'flex',
        background: 'var(--bg-dark)',
        borderRadius: 8,
        border: '1px solid var(--border)',
        overflow: 'hidden',
        marginBottom: 8,
      }}>
        <div style={{
          flex: 1, padding: '7px 0', textAlign: 'center',
          background: isSolar ? '#142214' : 'transparent',
          borderRight: '1px solid var(--border)',
          transition: 'background 0.3s',
        }}>
          <div style={{ fontSize: 14 }}>☀️</div>
          <div style={{ fontSize: 9, fontWeight: 700, color: isSolar ? 'var(--green)' : 'var(--text-dim)', marginTop: 2 }}>
            SOLAR
          </div>
        </div>
        <div style={{
          flex: 1, padding: '7px 0', textAlign: 'center',
          background: !isSolar ? '#1a0a2a' : 'transparent',
          transition: 'background 0.3s',
        }}>
          <div style={{ fontSize: 14 }}>⚡</div>
          <div style={{ fontSize: 9, fontWeight: 700, color: !isSolar ? 'var(--color-grid)' : 'var(--text-dim)', marginTop: 2 }}>
            STATE
          </div>
        </div>
      </div>

      {/* TTD */}
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
        <span style={{ color: 'var(--text-secondary)' }}>Time-to-Deficit</span>
        <span className="mono" style={{
          color: state.ttd_seconds < 120 ? 'var(--red)' : state.ttd_seconds < 300 ? 'var(--yellow)' : 'var(--green)'
        }}>
          {fmtTtd(state.ttd_seconds)}
        </span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
        <span style={{ color: 'var(--text-secondary)' }}>Break-even TTD</span>
        <span className="mono" style={{ color: 'var(--text-primary)' }}>
          {state.breakeven_ttd > 0 ? `${Math.round(state.breakeven_ttd)}s` : 'N/A'}
        </span>
      </div>

      {/* Dim T4 recommendation */}
      {state.dim_t4_recommended && (
        <div style={{
          fontSize: 9, color: 'var(--yellow)', background: '#2a2000',
          border: '1px solid #4a3800', borderRadius: 4, padding: '3px 7px', marginBottom: 4,
        }}>
          ⚠ Optimizer: Dim T4 recommended
        </div>
      )}

      {/* Mayor policy */}
      {state.active_policy !== 'None' && (
        <div style={{
          fontSize: 9, color: '#CE93D8', background: '#1a0a2a',
          border: '1px solid #3a1a5a', borderRadius: 4, padding: '3px 7px',
        }}>
          📋 {state.active_policy}
        </div>
      )}
      {policyCountdown && (
        <div style={{ marginTop: 4, fontSize: 9, color: 'var(--text-secondary)' }}>
          Expires in {policyCountdown}
        </div>
      )}

      {/* Active button */}
      {state.button > 0 && (
        <div style={{ marginTop: 4, fontSize: 9, color: 'var(--text-dim)' }}>
          Button {state.button}: {POLICY_LABELS[state.button] ?? 'Unknown'}
        </div>
      )}
    </div>
  );
}
