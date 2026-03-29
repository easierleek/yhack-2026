import type { InfrastructureNode } from '../data/infrastructure';
import type { NeoState, TierKey } from '../types/NeoState';
import { TIER_DEFS } from '../types/NeoState';
import { tierAvgPwm } from '../utils/pwm';
import { SocGauge } from './sidebar/SocGauge';
import { RewardScore } from './sidebar/RewardScore';
import { EnergyPrice } from './sidebar/EnergyPrice';
import { RelayStatus } from './sidebar/RelayStatus';
import { WeatherPanel } from './sidebar/WeatherPanel';
import { ReasoningFeed } from './sidebar/ReasoningFeed';

interface Props {
  state: NeoState;
  selectedZone: TierKey | null;
  selectedNode: InfrastructureNode | null;
  onClearSelection: () => void;
}

const DETAIL_COPY: Record<TierKey, { title: string; description: string; emphasis: string }> = {
  T1: {
    title: 'T1 Critical Care',
    description: 'Hospital infrastructure around Yale New Haven must remain fully energized. These sites anchor the visual map and the control policy.',
    emphasis: 'Best practice: preserve headroom, avoid any dimming, and surface outages immediately.',
  },
  T2: {
    title: 'T2 Core Utilities',
    description: 'Power, substation, and water assets support the district. Their footprint is compact but operationally sensitive during deficits.',
    emphasis: 'Best practice: degrade gracefully only after verifying T1 continuity and relay strategy.',
  },
  T3: {
    title: 'T3 Residential Load',
    description: 'Residential neighborhoods represent demand-following zones. They should feel alive on the map while remaining secondary to lifesafety tiers.',
    emphasis: 'Best practice: align brightness with modeled demand to reduce mismatch penalties.',
  },
  T4: {
    title: 'T4 Commercial Flex',
    description: 'Commercial corridors are the primary flex tier. They carry strong visual presence and should communicate dimming decisions clearly.',
    emphasis: 'Best practice: use this tier for economic optimization before touching critical service.',
  },
};

export function Sidebar({ state, selectedZone, selectedNode, onClearSelection }: Props) {
  const detailTier = selectedZone ? TIER_DEFS.find((tier) => tier.key === selectedZone) : null;
  const detailPwm = detailTier ? Math.round((tierAvgPwm(state.pwm, detailTier.key) / 255) * 100) : null;
  const nodePwm = selectedNode ? Math.round(((state.pwm[selectedNode.channel] ?? 0) / 255) * 100) : null;

  return (
    <div className="info-panel-content">
      <section className="panel-hero card-surface">
        <div>
          <p className="eyebrow">New Haven / Yale</p>
          <h2>Live grid map</h2>
          <p className="hero-copy">
            A dark Mini Motorways-inspired operations view with simplified real roads, square campus blocks, and ambient traffic.
          </p>
        </div>
        <div className="hero-pills">
          <span className="hero-pill">{state.eia_live ? 'EIA Live' : 'Simulated Feed'}</span>
          <span className="hero-pill">{state.relay === 0 ? 'Solar-first' : 'Grid assist'}</span>
        </div>
      </section>

      {detailTier && detailPwm !== null && (
        <section className="tier-focus card-surface animate-fade-in">
          <div className="tier-focus-header">
            <div>
              <p className="eyebrow">Selected Infrastructure</p>
              <h3>{DETAIL_COPY[detailTier.key].title}</h3>
            </div>
            <button type="button" className="ghost-button" onClick={onClearSelection}>
              Clear
            </button>
          </div>
          <p className="tier-copy">{DETAIL_COPY[detailTier.key].description}</p>
          <div className="tier-stats-grid">
            <Stat label="Tier" value={detailTier.key} accent={detailTier.color} />
            <Stat label="Brightness" value={`${detailPwm}%`} accent={detailTier.color} />
            <Stat label="Channels" value={detailTier.channels.join(', ')} />
            <Stat label="Policy" value={state.active_policy || 'None'} />
          </div>
          <p className="tier-emphasis">{DETAIL_COPY[detailTier.key].emphasis}</p>
        </section>
      )}

      {selectedNode && nodePwm !== null && (
        <section className="tier-focus card-surface animate-fade-in">
          <div className="tier-focus-header">
            <div>
              <p className="eyebrow">Infrastructure Detail</p>
              <h3>{selectedNode.name}</h3>
            </div>
            <button type="button" className="ghost-button" onClick={onClearSelection}>
              Clear
            </button>
          </div>
          <p className="tier-copy">{selectedNode.description}</p>
          <div className="tier-stats-grid">
            <Stat label="Tier" value={selectedNode.tier} />
            <Stat label="Load" value={`${nodePwm}%`} />
            <Stat label="District" value={selectedNode.district} />
            <Stat label="Role" value={selectedNode.role} />
          </div>
          <p className="tier-emphasis">{selectedNode.recommendedAction}</p>
        </section>
      )}

      <div className="panel-section-grid">
        <SocGauge state={state} />
        <RewardScore state={state} />
        <EnergyPrice state={state} />
        <RelayStatus state={state} />
        <WeatherPanel state={state} />
      </div>

      <ReasoningFeed state={state} />
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="tier-stat">
      <span>{label}</span>
      <strong style={accent ? { color: accent } : undefined}>{value}</strong>
    </div>
  );
}
