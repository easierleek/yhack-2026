# ============================================================
#  NEO — Nodal Energy Oracle
#  backend/forecaster.py  —  Predictive Analytics Engine
#  YHack 2025
#
#  ROLE: AI / Backend Engineer (Turtle) owns this file.
#
#  Every control cycle, main.py calls compute_forecast() and
#  merges the result into the K2 context dict.  This gives K2
#  pre-computed predictive signals so it doesn't have to
#  re-derive them from raw sensor deltas itself.
#
#  Signals produced
#  ─────────────────
#  ttd_seconds          — seconds until virtual battery hits 0
#  storm_probability    — 0.0-1.0 likelihood of incoming storm/clouds
#  solar_time_remaining — seconds until solar output reaches 0
#  mins_to_demand_spike — sim-minutes until next duck-curve spike
#  t2_demand_factor     — temperature-based T2 load multiplier
#  dim_t4_recommended   — bool: proactive dim beats relay click
#  breakeven_ttd        — TTD threshold below which dimming wins
#  market_penalty_active— bool: market price too high to use relay
#
#  ADVANCED FEATURES (new):
#  ─────────────────────────
#  Statistical features from history:
#    - light_volatility, pressure_volatility — sensor stability
#    - light_momentum, pressure_momentum — rate of change
#    - light_acceleration, pressure_acceleration — 2nd derivative
#    - percentile ranks — is current reading historically high/low?
#
#  Monte Carlo scenarios (new):
#    - scenarios — list of 3-5 plausible futures with probabilities
#    - expected_battery_5m — probability-weighted battery outcome
#    - relay_probability — likelihood relay will be needed
# ============================================================

from __future__ import annotations

import math
from typing import Optional

# ── New: Advanced analytics modules ────────────────────────────────────────────
try:
    from feature_engineer import FeatureEngineer
    _FEATURE_ENG = True
except ImportError:
    _FEATURE_ENG = False

try:
    from scenario_simulator import ScenarioSimulator
    _SCENARIO_SIM = True
except ImportError:
    _SCENARIO_SIM = False

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
BATTERY_CAPACITY_MAH: float = 2000.0   # must match main.py

# Duck curve: expected residential demand fraction by integer sim-hour
DUCK_CURVE: dict[int, float] = {
    0:  0.20, 1:  0.15, 2:  0.10, 3:  0.10, 4:  0.10, 5:  0.20,
    6:  0.50, 7:  0.80, 8:  0.70, 9:  0.50, 10: 0.40, 11: 0.30,
    12: 0.25, 13: 0.25, 14: 0.30, 15: 0.35, 16: 0.50,
    17: 0.70, 18: 0.90, 19: 1.00, 20: 0.95, 21: 0.80,
    22: 0.60, 23: 0.40,
}

# ── Global singleton instances for advanced analytics ───────────────────────────
_feature_engineer = FeatureEngineer() if _FEATURE_ENG else None
_scenario_simulator = ScenarioSimulator() if _SCENARIO_SIM else None

# ─── 1. TIME TO DEFICIT ───────────────────────────────────────────────────────

def time_to_deficit(
    battery_soc: float,
    solar_ma:    float,
    load_ma:     float,
) -> float:
    """
    How many seconds until the virtual battery reaches 0% at the
    current net drain rate.

    Returns math.inf if solar is meeting or exceeding load (no deficit).

    Parameters
    ----------
    battery_soc : float   Current SoC, 0.0 – 1.0
    solar_ma    : float   Current solar output in mA
    load_ma     : float   Current city load in mA
    """
    net_drain = load_ma - solar_ma   # positive = draining
    if net_drain <= 0.0:
        return math.inf

    # mA·s of charge remaining
    remaining_mas = battery_soc * BATTERY_CAPACITY_MAH * 3600.0
    return remaining_mas / net_drain


# ─── 2. STORM / CLOUD PROBABILITY ────────────────────────────────────────────

def storm_probability(history: list[dict]) -> float:
    """
    Estimates the probability of an incoming storm or cloud-cover event.

    Uses two independent signals and combines them:
      1. Pressure slope  — falling pressure is the strongest storm predictor
      2. Light slope     — rapid dimming means clouds are already arriving

    Returns a value in [0.0, 1.0] rounded to 3 decimal places.
    """
    if len(history) < 3:
        return 0.0

    window = history[-min(10, len(history)):]
    n = max(len(window) - 1, 1)

    pres_vals  = [r["pressure_hpa"] for r in window]
    light_vals = [r["light"]        for r in window]

    pres_slope  = (pres_vals[-1]  - pres_vals[0])  / n
    light_slope = (light_vals[-1] - light_vals[0]) / n

    # Pressure: 1.0 at slope ≤ -0.5 hPa/sample, 0.0 at slope ≥ 0
    pressure_factor = max(0.0, min(1.0, -pres_slope / 0.5))

    # Light: 1.0 at slope ≤ -20 units/sample, 0.0 at slope ≥ 0
    cloud_factor = max(0.0, min(1.0, -light_slope / 20.0))

    # Pressure is slower but more reliable → weight it higher
    prob = pressure_factor * 0.65 + cloud_factor * 0.35
    return round(min(1.0, prob), 3)


# ─── 3. SOLAR EXHAUSTION TIME ─────────────────────────────────────────────────

def solar_time_remaining(history: list[dict]) -> float:
    """
    Extrapolates the current light-level slope to predict how many
    real-time seconds remain before solar output reaches zero.

    Returns math.inf if light is stable or rising.

    Note: this is the time until the *LDR reading* hits zero, which acts
    as the proxy for "solar panel no longer producing power."
    """
    if len(history) < 3:
        return math.inf

    window = history[-min(10, len(history)):]
    n = max(len(window) - 1, 1)

    light_vals  = [r["light"] for r in window]
    slope       = (light_vals[-1] - light_vals[0]) / n   # units per 100 ms sample

    if slope >= 0.0:
        return math.inf   # stable or improving

    current_light = max(float(light_vals[-1]), 1.0)   # avoid div-by-zero

    # samples_to_zero = current / |slope|; each sample = 100 ms
    samples_to_zero = current_light / abs(slope)
    return samples_to_zero * 0.1   # seconds


# ─── 4. DUCK CURVE SPIKE PREDICTION ──────────────────────────────────────────

def minutes_to_next_spike(
    sim_hour:        float,
    spike_threshold: float = 0.70,
) -> float:
    """
    Returns the number of simulated minutes until the next residential
    demand spike (duck_demand >= spike_threshold).

    Returns 0.0  if the grid is already in a spike.
    Returns 9999 if no spike is found in the next 24 sim-hours (shouldn't
                 happen with default threshold).

    Parameters
    ----------
    sim_hour        : float   Current simulated hour (0.0 – 23.9)
    spike_threshold : float   Demand fraction that counts as a spike
    """
    current_demand = DUCK_CURVE[int(sim_hour) % 24]
    if current_demand >= spike_threshold:
        return 0.0

    for minutes_ahead in range(1, 24 * 60 + 1):
        future_hour   = (sim_hour + minutes_ahead / 60.0) % 24.0
        future_demand = DUCK_CURVE[int(future_hour) % 24]
        if future_demand >= spike_threshold:
            return float(minutes_ahead)

    return 9999.0


# ─── 5. TEMPERATURE-BASED T2 DEMAND FACTOR ───────────────────────────────────

def t2_demand_factor(temp_c: float) -> float:
    """
    Returns a multiplier (1.0 – 1.5) for Tier 2 (utilities/industry) demand.

    Extreme heat  → increased cooling load.
    Extreme cold  → increased heating load.
    Moderate temp → base demand.

    The AI can multiply its T2 target PWM by this factor to reflect
    realistic industrial energy consumption.
    """
    if   temp_c > 35: return 1.50
    elif temp_c > 28: return 1.20
    elif temp_c < 5:  return 1.50
    elif temp_c < 12: return 1.20
    else:             return 1.00


# ─── 6. RELAY BREAK-EVEN OPTIMIZER ───────────────────────────────────────────

def relay_break_even(
    battery_soc:     float,
    solar_ma:        float,
    load_ma:         float,
    market_price:    float,
    penalty_weights: dict,
) -> dict:
    """
    Answers the core optimization question every cycle:

        Is it cheaper (in reward points) to proactively dim Tier 4 NOW,
        or to keep T4 bright and accept an inevitable relay click LATER?

    Math
    ────
    Let  R  = relay click penalty               (e.g. 500 pts)
    Let  D  = net cost of fully dimming T4/sec
                = (T4 dim penalty/sec) + (T4 revenue forgone/sec)
    Let  T  = time to battery deficit in seconds

    Break-even TTD  = R / D
    → If T < break-even TTD, dimming now is cheaper than the relay click.
    → Add a 1.5× safety margin so we dim early, not at the last second.

    Returns
    -------
    dict with keys:
        dim_now           bool   — True if proactive dim is recommended
        ttd_seconds       float  — seconds until deficit (99999 = no deficit)
        relay_cost        float  — relay penalty magnitude in pts
        t4_dim_cost_ps    float  — net reward cost of fully dimming T4 per second
        t4_total_dim_cost float  — total cost of dimming until crisis point
        breakeven_ttd     float  — TTD threshold below which dimming wins
        market_penalty    bool   — True if market price alone warrants avoiding relay
        recommended_t4    int    — suggested T4 PWM value (0-255) this cycle
    """
    ttd     = time_to_deficit(battery_soc, solar_ma, load_ma)
    r_cost  = abs(penalty_weights.get("relay_click",   -500))
    d_p10   = abs(penalty_weights.get("tier4_per10",   -5))
    revenue = penalty_weights.get("tier4_revenue",     +10)

    # ── Per-second cost of keeping T4 fully dim ───────────────────────────────
    # 10 cycles/s, 6 channels, 100% dim = 10 bands of 10%
    # Revenue uses * 0.1 per-cycle factor in compute_reward — must match here.
    dim_penalty_per_sec     = d_p10 * 10 * 10 * 6          # 10 bands × 10 cycles × 6 ch = 3000
    revenue_forgone_per_sec = revenue * 0.1 * 10 * 6       # 0.1 per-cycle × 10 cycles × 6 ch = 60
    t4_dim_cost_ps = dim_penalty_per_sec + revenue_forgone_per_sec

    # ── Total cost over the time until crisis ────────────────────────────────
    ttd_capped        = min(ttd, 600.0)   # cap at 10 min to avoid huge numbers
    t4_total_dim_cost = t4_dim_cost_ps * ttd_capped

    # ── Break-even threshold (with 1.5× early-action margin) ─────────────────
    breakeven_ttd = r_cost / max(t4_dim_cost_ps, 1.0)

    # ── Market price check ───────────────────────────────────────────────────
    market_penalty = market_price > 2.0

    # ── Decision ─────────────────────────────────────────────────────────────
    # Dim if:  a) deficit is arriving in < 60 seconds, OR
    #          b) market price alone makes the relay too expensive
    dim_now = (ttd < 60.0) or market_penalty

    return {
        "dim_now":            dim_now,
        "ttd_seconds":        round(ttd if ttd != math.inf else 99999.0, 1),
        "relay_cost":         r_cost,
        "t4_dim_cost_ps":     round(t4_dim_cost_ps, 2),
        "t4_total_dim_cost":  round(t4_total_dim_cost, 1),
        "breakeven_ttd":      round(breakeven_ttd, 1),
        "market_penalty":     market_penalty,
    }


# ─── 7. FULL FORECAST BUNDLE ─────────────────────────────────────────────────

def compute_forecast(
    history:         list[dict],
    battery_soc:     float,
    solar_ma:        float,
    load_ma:         float,
    temp_c:          float,
    sim_hour:        float,
    market_price:    float,
    penalty_weights: dict,
) -> dict:
    """
    Master entry point — computes all predictive signals in one call and
    returns a flat dict ready to be merged into the K2 context object via:

        context = {**sensor, **compute_forecast(...), ...other fields...}

    Parameters
    ----------
    history         : list of recent sensor dicts (up to 20)
    battery_soc     : current virtual SoC (0.0–1.0)
    solar_ma        : current solar current in mA
    load_ma         : current city load in mA
    temp_c          : current temperature in Celsius
    sim_hour        : current simulated hour (0.0–23.9)
    market_price    : current EIA-blended electricity price ($/kWh)
    penalty_weights : active reward weights (from PolicyEngine or base dict)

    Returns
    -------
    dict — flat, JSON-serialisable, ready to merge into K2 context
    """
    storm_prob = storm_probability(history)
    solar_tr   = solar_time_remaining(history)
    mins_spike = minutes_to_next_spike(sim_hour)
    t2_factor  = t2_demand_factor(temp_c)
    beven      = relay_break_even(
        battery_soc, solar_ma, load_ma, market_price, penalty_weights
    )

    # Compute light and pressure slopes for K2 (still useful raw signals)
    sun_slope      = _slope(history, "light")
    pressure_slope = _slope(history, "pressure_hpa")

    # ── NEW: Advanced feature engineering ──────────────────────────────────────
    advanced_features = {}
    scenarios_data = {}
    
    if _FEATURE_ENG and _feature_engineer:
        # Update feature engineer with latest sensor reading
        if history:
            _feature_engineer.update(history[-1])
        
        # Compute all statistical features
        advanced_features = _feature_engineer.compute_all_features()
    
    if _SCENARIO_SIM and _scenario_simulator:
        # Generate Monte Carlo scenarios
        scenarios = _scenario_simulator.generate_scenarios(
            battery_soc=battery_soc,
            storm_probability=storm_prob,
            solar_ma=solar_ma,
            load_ma=load_ma,
            temp_c=temp_c,
            market_price=market_price,
            t2_demand_factor=t2_factor,
            time_horizon_minutes=5.0,
        )
        
        # Compute weighted outcome
        weighted = _scenario_simulator.compute_weighted_outcome(scenarios)
        
        # Serialize scenarios for K2 (convert to simple dicts for JSON)
        scenarios_data = {
            "scenarios_count": len(scenarios),
            "dominant_scenario": weighted.get("dominant_scenario", "Unknown"),
            "dominant_probability": weighted.get("dominant_probability", 0.0),
            "expected_battery_5m_percent": weighted.get("expected_battery_5m_percent", battery_soc * 100),
            "relay_probability": weighted.get("relay_probability", 0.0),
            "scenario_recommendation": weighted.get("recommendation", "Maintain current power levels"),
        }

    return {
        # ── Core predictive signals (RAW, for K2 to reason with) ──────────────
        "storm_probability":      storm_prob,
        "solar_time_remaining":   round(solar_tr  if solar_tr  != math.inf else 99999.0, 1),
        "mins_to_demand_spike":   round(mins_spike if mins_spike != 9999.0  else 9999.0,  1),
        "t2_demand_factor":       round(t2_factor, 2),

        # ── Economic break-even data (inputs to K2's reasoning) ────────────────
        "dim_t4_recommended":     beven["dim_now"],
        "ttd_seconds":            beven["ttd_seconds"],
        "breakeven_ttd":          beven["breakeven_ttd"],
        "market_penalty_active":  beven["market_penalty"],

        # ── Raw slopes (signals for K2 to interpret) ──────────────────────────
        "sun_slope":              round(sun_slope,      2),
        "pressure_slope":         round(pressure_slope, 4),
        
        # ── NEW: Advanced statistical features (for sophisticated reasoning) ──
        **advanced_features,
        
        # ── NEW: Monte Carlo scenarios (for probability-weighted decisions) ────
        **scenarios_data,
    }


# ─── INTERNAL HELPER ──────────────────────────────────────────────────────────

def _slope(history: list[dict], key: str, window: int = 5) -> float:
    """
    Simple linear slope of `key` over the last `window` sensor samples.
    Returns 0.0 if there is insufficient history.
    """
    if len(history) < 2:
        return 0.0
    recent = history[-window:]
    vals   = [r[key] for r in recent]
    return (vals[-1] - vals[0]) / max(len(vals) - 1, 1)
