import { TIER_DEFS } from '../types/NeoState';
import type { TierKey } from '../types/NeoState';

/** Map PWM 0-255 → opacity 0.08–1.0. Never fully dark so zones stay readable. */
export function pwmToOpacity(pwm: number): number {
  return Math.max(0.08, Math.min(1.0, pwm / 255));
}

/** Average PWM across a tier's channels. */
export function tierAvgPwm(pwm: number[], key: TierKey): number {
  const def = TIER_DEFS.find(t => t.key === key);
  if (!def) return 0;
  const vals = def.channels.map(ch => pwm[ch] ?? 0);
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

/** Format TTD seconds as human-readable string. */
export function fmtTtd(seconds: number): string {
  if (seconds >= 99990) return 'No deficit';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

/** Format sim hour (0-24 float) as HH:MM. */
export function fmtSimHour(simHour: number): string {
  const h = Math.floor(simHour) % 24;
  const m = Math.floor((simHour - Math.floor(simHour)) * 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

/** Time-of-day icon for sim hour. */
export function todIcon(simHour: number): string {
  const h = Math.floor(simHour) % 24;
  if (h < 6 || h >= 22) return '🌙';
  if (h < 9) return '🌅';
  if (h < 18) return '☀️';
  return '🌆';
}

/** Clamp a value to [min, max]. */
export function clamp(val: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, val));
}

/** Map a value from [inMin, inMax] to [outMin, outMax]. */
export function mapRange(
  val: number,
  inMin: number, inMax: number,
  outMin: number, outMax: number,
): number {
  const t = clamp((val - inMin) / (inMax - inMin), 0, 1);
  return outMin + t * (outMax - outMin);
}
