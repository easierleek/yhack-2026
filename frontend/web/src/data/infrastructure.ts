import type { TierKey } from '../types/NeoState';

export type InfrastructureCategory = 'residential' | 'commercial' | 'hospital' | 'utility';

export interface InfrastructureNode {
  id: string;
  name: string;
  sub: string;
  category: InfrastructureCategory;
  tier: TierKey;
  lat: number;
  lng: number;
  channel: number;
  district: string;
  role: string;
  description: string;
  recommendedAction: string;
}

export const INFRASTRUCTURE_NODES: InfrastructureNode[] = [
  {
    id: 'yale-new-haven',
    name: 'Yale New Haven',
    sub: 'Hospital',
    category: 'hospital',
    tier: 'T1',
    lat: 41.3037,
    lng: -72.9348,
    channel: 0,
    district: 'Downtown / Medical Core',
    role: 'Regional emergency care campus',
    description: 'Primary hospital load that anchors the critical-care tier and should remain fully energized through every policy state.',
    recommendedAction: 'Preserve full continuity and keep reserve headroom available before shedding any adjacent flexible load.',
  },
  {
    id: 'st-raphael',
    name: 'St. Raphael',
    sub: 'Chapel Campus',
    category: 'hospital',
    tier: 'T1',
    lat: 41.307,
    lng: -72.9442,
    channel: 1,
    district: 'West Medical Corridor',
    role: 'Critical care support campus',
    description: 'Secondary hospital campus supporting acute care, clinics, and overflow medical demand around Chapel Street.',
    recommendedAction: 'Hold at full service and surface any instability immediately to avoid cascading impact on clinical operations.',
  },
  {
    id: 'english-station',
    name: 'English Station',
    sub: 'Power Plant',
    category: 'utility',
    tier: 'T2',
    lat: 41.3112,
    lng: -72.907,
    channel: 2,
    district: 'Mill River',
    role: 'Utility generation asset',
    description: 'High-visibility utility node on the east side that represents bulk energy support and resilience capacity.',
    recommendedAction: 'Keep stable under high-price events and only degrade after T1 continuity and relay strategy are confirmed.',
  },
  {
    id: 'harbor-sub',
    name: 'Harbor Substation',
    sub: 'Utility',
    category: 'utility',
    tier: 'T2',
    lat: 41.282,
    lng: -72.905,
    channel: 3,
    district: 'Long Wharf / Harbor',
    role: 'Waterfront grid transfer node',
    description: 'Harbor-side utility infrastructure linking downtown demand to the larger waterfront transmission footprint.',
    recommendedAction: 'Maintain clean relay handoffs here during solar-to-grid transitions to avoid avoidable brownout penalties.',
  },
  {
    id: 'westville-res',
    name: 'Westville',
    sub: 'Residential',
    category: 'residential',
    tier: 'T3',
    lat: 41.318,
    lng: -72.96,
    channel: 5,
    district: 'Westville',
    role: 'Residential neighborhood demand',
    description: 'Neighborhood-scale residential load that should feel alive on the map while remaining secondary to life-safety systems.',
    recommendedAction: 'Track modeled demand and trim smoothly if balancing pressure rises across the district.',
  },
  {
    id: 'dixwell-res',
    name: 'Dixwell',
    sub: 'Residential',
    category: 'residential',
    tier: 'T3',
    lat: 41.32,
    lng: -72.938,
    channel: 6,
    district: 'Dixwell / Newhallville Edge',
    role: 'Dense mixed residential load',
    description: 'A denser residential demand pocket near the medical and downtown core, sensitive to mismatched dimming.',
    recommendedAction: 'Favor gradual modulation here and align with forecasted demand spikes rather than abrupt cuts.',
  },
  {
    id: 'fair-haven-res',
    name: 'Fair Haven',
    sub: 'Residential',
    category: 'residential',
    tier: 'T3',
    lat: 41.31,
    lng: -72.898,
    channel: 7,
    district: 'Fair Haven',
    role: 'East-side residential demand',
    description: 'Residential east-side demand with long feeder paths and visible dependence on stable secondary-road infrastructure.',
    recommendedAction: 'Use this node as a demand-following buffer before reaching into utility-critical or medical capacity.',
  },
  {
    id: 'downtown-com',
    name: 'Downtown',
    sub: 'Commercial',
    category: 'commercial',
    tier: 'T4',
    lat: 41.306,
    lng: -72.927,
    channel: 10,
    district: 'Downtown Core',
    role: 'Commercial flex corridor',
    description: 'Commercial flex load around the civic core that can absorb optimization-driven dimming before critical tiers are touched.',
    recommendedAction: 'Use as the first lever for economic optimization and communicate dimming clearly when market pressure rises.',
  },
];
