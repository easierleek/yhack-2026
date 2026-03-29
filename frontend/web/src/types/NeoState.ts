export interface NeoState {
  // Grid
  battery_soc: number;
  sim_hour: number;
  market_price: number;
  relay: 0 | 1;
  reward_score: number;
  // Sensors
  light: number;
  temp_c: number;
  pressure_hpa: number;
  solar_ma: number;
  load_ma: number;
  pot1: number;
  pot2: number;
  tilt: 0 | 1;
  button: number;
  // Forecast
  sun_slope: number;
  pressure_slope: number;
  duck_demand: number;
  storm_probability: number;
  ttd_seconds: number;
  solar_time_remaining: number;
  t2_demand_factor: number;
  breakeven_ttd: number;
  market_penalty_active: boolean;
  dim_t4_recommended: boolean;
  recommended_t4_pwm: number;
  mins_to_demand_spike: number;
  // AI
  pwm: number[];   // length 16: ch0-1=T1, ch2-4=T2, ch5-9=T3, ch10-15=T4
  reasoning: string;
  reasoning_feed: [number, string][];
  // EIA
  eia_retail: number;
  eia_demand_mw: number;
  eia_live: boolean;
  eia_age_s: number;
  // Policy
  active_policy: string;
  active_policies?: string[];
  policy_expires_in?: number;
  policy_real_expires?: number;
  // Meta
  fault: string;
  loop_ms: number;
  k2_calls: number;
}

export const DEFAULT_STATE: NeoState = {
  battery_soc: 0.5,
  sim_hour: 0,
  market_price: 1.0,
  relay: 0,
  reward_score: 0,
  light: 512,
  temp_c: 25,
  pressure_hpa: 1013.25,
  solar_ma: 0,
  load_ma: 0,
  pot1: 512,
  pot2: 512,
  tilt: 0,
  button: 0,
  sun_slope: 0,
  pressure_slope: 0,
  duck_demand: 0.5,
  storm_probability: 0,
  ttd_seconds: 99999,
  solar_time_remaining: 99999,
  t2_demand_factor: 1,
  breakeven_ttd: 0,
  market_penalty_active: false,
  dim_t4_recommended: false,
  recommended_t4_pwm: 255,
  mins_to_demand_spike: 9999,
  pwm: [255, 255, 255, 255, 255, 200, 200, 200, 200, 200, 128, 128, 128, 128, 128, 128],
  reasoning: 'Waiting for first AI cycle...',
  reasoning_feed: [],
  eia_retail: 0.17,
  eia_demand_mw: 400000,
  eia_live: false,
  eia_age_s: 0,
  active_policy: 'None',
  active_policies: [],
  policy_expires_in: 0,
  policy_real_expires: 0,
  fault: '',
  loop_ms: 0,
  k2_calls: 0,
};

export type TierKey = 'T1' | 'T2' | 'T3' | 'T4';

export interface TierDef {
  key: TierKey;
  label: string;
  channels: number[];
  color: string;
  glow: string;
  darkColor: string;
}

export const TIER_DEFS: TierDef[] = [
  { key: 'T1', label: 'Hospitals',   channels: [0, 1],              color: '#D0EEFF', glow: '#FFFFFF', darkColor: '#8BC4E8' },
  { key: 'T2', label: 'Utilities',   channels: [2, 3, 4],           color: '#FF8B94', glow: '#FF5566', darkColor: '#C85060' },
  { key: 'T3', label: 'Residential', channels: [5, 6, 7, 8, 9],    color: '#A8E6CF', glow: '#5BFFA0', darkColor: '#5BAE80' },
  { key: 'T4', label: 'Commercial',  channels: [10, 11, 12, 13, 14, 15], color: '#FFE082', glow: '#FFD740', darkColor: '#C8A840' },
];
