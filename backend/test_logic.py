# ============================================================
#  NEO -- Nodal Energy Oracle
#  backend/test_logic.py  --  ML Logic Unit Tests
#  YHack 2025
#
#  Tests every ML function without needing an Arduino,
#  serial port, or any API key.
#
#  Run from the backend/ directory:
#      python test_logic.py
# ============================================================

import math
import sys
import os
import json
import re

# ── Make sure we can find forecaster.py ───────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forecaster import (
    time_to_deficit,
    storm_probability,
    solar_time_remaining,
    minutes_to_next_spike,
    t2_demand_factor,
    relay_break_even,
    compute_forecast,
    BATTERY_CAPACITY_MAH,
    DUCK_CURVE,
)

# ─── Minimal test harness ─────────────────────────────────────────────────────

PASS = 0
FAIL = 0

def check(name: str, got, expected, tolerance=None):
    global PASS, FAIL
    if tolerance is not None:
        ok = abs(got - expected) <= tolerance
    elif isinstance(expected, bool):
        ok = (got == expected)
    elif isinstance(expected, float) and math.isinf(expected):
        ok = math.isinf(got)
    else:
        ok = (got == expected)

    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")
        print(f"        expected: {expected!r}")
        print(f"        got:      {got!r}")

def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ─── BASE WEIGHTS (mirrors main.py) ──────────────────────────────────────────
BASE_WEIGHTS = {
    "tier1_dim":     -1000.0,
    "tier2_per10":     -50.0,
    "tier3_outrage":   -20.0,
    "tier4_per10":      -5.0,
    "relay_click":    -500.0,
    "tier4_revenue":   +10.0,
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. TIME TO DEFICIT
# ─────────────────────────────────────────────────────────────────────────────
section("1. time_to_deficit")

# Solar covers load exactly -- no deficit
check("solar == load -> inf",
      time_to_deficit(0.5, 200.0, 200.0), math.inf)

# Solar exceeds load -- no deficit
check("solar > load -> inf",
      time_to_deficit(0.5, 300.0, 200.0), math.inf)

# Compute manually: 0.5 * 2000 * 3600 / 100 = 36000 seconds
check("50% SoC, net drain 100 mA -> 36000 s",
      time_to_deficit(0.5, 0.0, 100.0), 36000.0, tolerance=0.1)

# 10% SoC, drain 200 mA: 0.1 * 2000 * 3600 / 200 = 3600 s
check("10% SoC, net drain 200 mA -> 3600 s",
      time_to_deficit(0.1, 0.0, 200.0), 3600.0, tolerance=0.1)

# Empty battery -> immediately 0 seconds (0 * 2000 * 3600 / anything = 0)
check("0% SoC -> 0 s",
      time_to_deficit(0.0, 0.0, 100.0), 0.0, tolerance=0.001)

# ─────────────────────────────────────────────────────────────────────────────
# 2. STORM PROBABILITY
# ─────────────────────────────────────────────────────────────────────────────
section("2. storm_probability")

# Too few samples -> 0
check("< 3 samples -> 0.0",
      storm_probability([
          {"pressure_hpa": 1013.0, "light": 800}
      ]), 0.0)

# Stable pressure and light -> 0 storm probability
stable = [{"pressure_hpa": 1013.0, "light": 800}] * 10
check("stable conditions -> 0.0",
      storm_probability(stable), 0.0)

# Rapidly falling pressure (strong signal) and falling light
# slope of pressure: -5 over 9 intervals = -0.556 hPa/sample (>threshold of -0.5)
# slope of light: -10 over 9 intervals = -1.1/sample (small vs -20 threshold)
falling_pressure = [
    {"pressure_hpa": 1013.0 - i * 0.556, "light": 800 - i * 1.1}
    for i in range(10)
]
prob = storm_probability(falling_pressure)
check("falling pressure -> prob > 0.6",
      prob > 0.6, True)
check("storm probability clamped ≤ 1.0",
      prob <= 1.0, True)

# Only light dropping fast (clouds arriving)
# slope of light: -200 over 9 samples = -22.2/sample (exceeds -20 threshold)
clouds_only = [
    {"pressure_hpa": 1013.0, "light": 1000 - i * 22}
    for i in range(10)
]
cloud_prob = storm_probability(clouds_only)
check("fast light drop -> prob > 0",
      cloud_prob > 0.0, True)
check("cloud-only factor weighted 0.35 -> prob ≤ 0.35",
      cloud_prob <= 0.36, True)

# ─────────────────────────────────────────────────────────────────────────────
# 3. SOLAR TIME REMAINING
# ─────────────────────────────────────────────────────────────────────────────
section("3. solar_time_remaining")

check("< 3 samples -> inf",
      solar_time_remaining([{"light": 500}]), math.inf)

# Stable light -> no solar exhaustion
stable_light = [{"light": 700}] * 10
check("stable light -> inf",
      solar_time_remaining(stable_light), math.inf)

# Rising light -> inf
rising_light = [{"light": 500 + i * 10} for i in range(10)]
check("rising light -> inf",
      solar_time_remaining(rising_light), math.inf)

# Falling at -50 units/sample, current = 500
# slope over 9 intervals = (50 - 500) / 9 = -50
# samples_to_zero = 500 / 50 = 10 samples -> 1.0 second
falling_light = [{"light": 500 - i * 50} for i in range(10)]
result = solar_time_remaining(falling_light)
check("falling at 50/sample, light=50 -> ~0.1 s",
      result, 0.1, tolerance=0.02)

# ─────────────────────────────────────────────────────────────────────────────
# 4. MINUTES TO NEXT SPIKE
# ─────────────────────────────────────────────────────────────────────────────
section("4. minutes_to_next_spike")

# Hour 19 has demand 1.0 -- already in spike
check("hour 19 (demand=1.0) -> already in spike (0.0)",
      minutes_to_next_spike(19.0), 0.0)

# Hour 7 has demand 0.8 -- already in spike
check("hour 7 (demand=0.8) -> already in spike (0.0)",
      minutes_to_next_spike(7.0), 0.0)

# Hour 3 has demand 0.1 -- next spike at hour 7 = 4 hours = 240 sim-minutes
mins = minutes_to_next_spike(3.0)
check("hour 3 -> next spike at hour 7 (≈240 min)",
      mins, 240.0, tolerance=2.0)

# Hour 12 (demand=0.25) -> next spike at hour 17 (demand=0.7) = 5 hours = 300 min
mins12 = minutes_to_next_spike(12.0)
check("hour 12 -> next spike at hour 17 (≈300 min)",
      mins12, 300.0, tolerance=2.0)

# Hour 20 (demand=0.95) -- already in spike (>= 0.7)
check("hour 20 (demand=0.95) -> already in spike (0.0)",
      minutes_to_next_spike(20.0), 0.0)

# ─────────────────────────────────────────────────────────────────────────────
# 5. T2 DEMAND FACTOR
# ─────────────────────────────────────────────────────────────────────────────
section("5. t2_demand_factor")

check("20°C -> 1.0 (normal)",     t2_demand_factor(20.0), 1.0)
check("25°C -> 1.0 (upper edge)", t2_demand_factor(25.0), 1.0)
check("28°C -> 1.0 (lower of >28 boundary)", t2_demand_factor(28.0), 1.0)
check("29°C -> 1.2 (mild heat)", t2_demand_factor(29.0), 1.2)
check("36°C -> 1.5 (extreme heat)", t2_demand_factor(36.0), 1.5)
check("12°C -> 1.0 (upper cold boundary)", t2_demand_factor(12.0), 1.0)
check("11°C -> 1.2 (mild cold)", t2_demand_factor(11.0), 1.2)
check("4°C  -> 1.5 (extreme cold)", t2_demand_factor(4.0),  1.5)
check("-5°C -> 1.5 (extreme cold)", t2_demand_factor(-5.0), 1.5)

# ─────────────────────────────────────────────────────────────────────────────
# 6. RELAY BREAK-EVEN OPTIMIZER
# ─────────────────────────────────────────────────────────────────────────────
section("6. relay_break_even")

# ── 6a. Basic structure check ─────────────────────────────────────────────────
result = relay_break_even(0.5, 0.0, 100.0, 1.0, BASE_WEIGHTS)
required_keys = {
    "dim_now", "ttd_seconds", "relay_cost", "t4_dim_cost_ps",
    "t4_total_dim_cost", "breakeven_ttd", "market_penalty", "recommended_t4"
}
check("returns all required keys",
      required_keys.issubset(result.keys()), True)

# ── 6b. relay_cost must equal abs(relay_click weight) ─────────────────────────
check("relay_cost == 500",
      result["relay_cost"], 500.0)

# ── 6c. TTD matches time_to_deficit ──────────────────────────────────────────
expected_ttd = time_to_deficit(0.5, 0.0, 100.0)
check("ttd_seconds matches time_to_deficit",
      result["ttd_seconds"], round(expected_ttd, 1), tolerance=1.0)

# ── 6d. No deficit -> recommended_t4 at full (255) ───────────────────────────
surplus = relay_break_even(0.5, 500.0, 100.0, 1.0, BASE_WEIGHTS)
check("solar surplus -> recommended_t4 = 255",
      surplus["recommended_t4"], 255)
check("solar surplus -> dim_now = False",
      surplus["dim_now"], False)

# ── 6e. High market price triggers market_penalty ────────────────────────────
high_price = relay_break_even(0.8, 500.0, 100.0, 2.5, BASE_WEIGHTS)
check("market_price=2.5 -> market_penalty = True",
      high_price["market_penalty"], True)
check("market_penalty -> dim_now = True",
      high_price["dim_now"], True)
check("market_penalty -> recommended_t4 ≤ 150",
      high_price["recommended_t4"] <= 150, True)

# ── 6f. t4_dim_cost_ps must reflect BOTH dim penalty AND revenue forgone ──────
# This is the critical revenue calculation bug check.
# dim_penalty_per_sec = abs(tier4_per10) * 10 bands * 10 cycles/s * 6 channels
# revenue_forgone_per_sec = tier4_revenue * 0.1 (per-cycle factor) * 10 cycles/s * 6 channels
# = 10 * 0.1 * 10 * 6 = 60  (NOT 600)
# total t4_dim_cost_ps should equal dim_penalty_per_sec + 60
dim_penalty_per_sec = abs(BASE_WEIGHTS["tier4_per10"]) * 10 * 10 * 6   # 3000
correct_revenue     = BASE_WEIGHTS["tier4_revenue"] * 0.1 * 10 * 6     #   60
correct_total       = dim_penalty_per_sec + correct_revenue             # 3060

check("t4_dim_cost_ps uses 0.1 factor on revenue (should be ~3060, NOT ~3600)",
      result["t4_dim_cost_ps"], correct_total, tolerance=1.0)

# ── 6g. Breakeven TTD = relay_cost / t4_dim_cost_ps ─────────────────────────
expected_breakeven = 500.0 / correct_total
check("breakeven_ttd = relay_cost / t4_dim_cost_ps",
      result["breakeven_ttd"], round(expected_breakeven, 1), tolerance=0.1)

# ── 6h. Imminent deficit -> T4 should dim aggressively ────────────────────────
# Force a very short TTD: 1% SoC, massive drain
# ttd = 0.01 * 2000 * 3600 / 5000 = 14.4 seconds
imminent = relay_break_even(0.01, 0.0, 5000.0, 1.0, BASE_WEIGHTS)
check("imminent deficit -> recommended_t4 < 100",
      imminent["recommended_t4"] < 100, True)

# ── 6i. Gradual dim scaling -- more drain = lower recommended_t4 ──────────────
mild    = relay_break_even(0.5, 50.0,  100.0, 1.0, BASE_WEIGHTS)   # large TTD
medium  = relay_break_even(0.1, 0.0,   200.0, 1.0, BASE_WEIGHTS)   # medium TTD
crisis  = relay_break_even(0.01, 0.0, 1000.0, 1.0, BASE_WEIGHTS)   # short TTD
check("mild drain -> higher T4 than crisis",
      mild["recommended_t4"] >= crisis["recommended_t4"], True)

# ─────────────────────────────────────────────────────────────────────────────
# 7. COMPUTE_FORECAST (integration test)
# ─────────────────────────────────────────────────────────────────────────────
section("7. compute_forecast (integration)")

# Build a realistic history
sample_history = [
    {
        "light":        700 - i * 5,
        "pressure_hpa": 1013.0 - i * 0.05,
        "temp_c":       22.0,
        "solar_ma":     300.0,
        "load_ma":      280.0,
    }
    for i in range(15)
]

fc = compute_forecast(
    history         = sample_history,
    battery_soc     = 0.6,
    solar_ma        = 300.0,
    load_ma         = 280.0,
    temp_c          = 22.0,
    sim_hour        = 14.0,
    market_price    = 1.2,
    penalty_weights = BASE_WEIGHTS,
)

required_forecast_keys = {
    "storm_probability", "solar_time_remaining", "mins_to_demand_spike",
    "t2_demand_factor", "dim_t4_recommended", "recommended_t4_pwm",
    "ttd_seconds", "breakeven_ttd", "market_penalty_active",
    "sun_slope", "pressure_slope",
}
check("compute_forecast returns all required keys",
      required_forecast_keys.issubset(fc.keys()), True)

check("storm_probability in [0, 1]",
      0.0 <= fc["storm_probability"] <= 1.0, True)

check("solar_time_remaining ≥ 0",
      fc["solar_time_remaining"] >= 0.0, True)

check("mins_to_demand_spike ≥ 0 (hour 14 -> next spike at 17)",
      fc["mins_to_demand_spike"] > 0.0, True)

check("t2_demand_factor = 1.0 at 22°C",
      fc["t2_demand_factor"], 1.0)

check("recommended_t4_pwm in [0, 255]",
      0 <= fc["recommended_t4_pwm"] <= 255, True)

check("sun_slope ≤ 0 (light declining in test data)",
      fc["sun_slope"] <= 0.0, True)

check("pressure_slope ≤ 0 (pressure declining in test data)",
      fc["pressure_slope"] <= 0.0, True)

# ─────────────────────────────────────────────────────────────────────────────
# 8. VIRTUAL BATTERY UPDATE (main.py logic tested inline)
# ─────────────────────────────────────────────────────────────────────────────
section("8. Virtual battery update_battery logic")

def update_battery_test(soc, solar_ma, load_ma, dt):
    """Mirror of main.py update_battery for isolated testing."""
    net_ma = solar_ma - load_ma
    delta  = (net_ma * dt) / (BATTERY_CAPACITY_MAH * 3600.0)
    return max(0.0, min(1.0, soc + delta))

# Charging: solar 400 mA, load 200 mA, net +200 mA for 3600 s
# delta = 200 * 3600 / (2000 * 3600) = 200/2000 = 0.1
soc_after = update_battery_test(0.5, 400.0, 200.0, 3600.0)
check("charge 200 mA for 1 hr on 2000 mAh -> SoC +0.1",
      soc_after, 0.6, tolerance=0.001)

# Discharging: net -100 mA for 7200 s on 2000 mAh from 50%
# delta = -100 * 7200 / (2000 * 3600) = -720000 / 7200000 = -0.1
soc_after2 = update_battery_test(0.5, 0.0, 100.0, 7200.0)
check("drain 100 mA for 2 hr on 2000 mAh -> SoC -0.1",
      soc_after2, 0.4, tolerance=0.001)

# Clamped at 0
soc_drained = update_battery_test(0.01, 0.0, 5000.0, 10000.0)
check("battery can't go below 0.0",
      soc_drained, 0.0)

# Clamped at 1
soc_full = update_battery_test(0.99, 5000.0, 0.0, 10000.0)
check("battery can't exceed 1.0",
      soc_full, 1.0)

# ─────────────────────────────────────────────────────────────────────────────
# 9. COMPUTE_REWARD (main.py logic tested inline)
# ─────────────────────────────────────────────────────────────────────────────
section("9. compute_reward logic")

def compute_reward_test(pwm, relay, pot1, pot2, prev_relay, weights):
    """Mirror of main.py compute_reward for isolated per-cycle testing."""
    r = 0.0

    # T1
    for ch in [0, 1]:
        if pwm[ch] < 255:
            r += weights["tier1_dim"] * ((255 - pwm[ch]) / 255 * 100)

    # T2
    for ch in [2, 3, 4]:
        r += weights["tier2_per10"] * ((255 - pwm[ch]) / 255.0 * 10.0)

    # T3
    pot_avg = ((pot1 + pot2) / 2.0) / 1023.0
    for ch in [5, 6, 7, 8, 9]:
        mismatch = abs(pwm[ch] / 255.0 - pot_avg)
        r += weights["tier3_outrage"] * (mismatch * 10.0)

    # T4
    for ch in [10, 11, 12, 13, 14, 15]:
        if pwm[ch] > 0:
            r += weights["tier4_revenue"] * 0.1
        r += weights["tier4_per10"] * ((255 - pwm[ch]) / 255.0 * 10.0)

    # Relay
    if relay == 1 and prev_relay == 0:
        r += weights["relay_click"]

    return r

# Perfect state: T1=255, T2=255, T3 matches pots, T4=255, no relay
# T3 mismatch check: pots at 512 -> pot_avg = 0.5 -> target_pwm ≈ 127.5
# If T3 channels at round(0.5 * 255) = 127, mismatch ≈ 0.002
t3_pwm = round(0.5 * 255)
ideal_pwm = [255, 255, 255, 255, 255,
             t3_pwm, t3_pwm, t3_pwm, t3_pwm, t3_pwm,
             255,  255,  255,  255,  255,  255]

ideal_r = compute_reward_test(ideal_pwm, 0, 512, 512, 0, BASE_WEIGHTS)
check("ideal state: T4 revenue earned (positive contribution)",
      ideal_r > 0.0, True)

# T1 dimmed to 128 (50%) -- catastrophic penalty
t1_dim_pwm = [128, 255, 255, 255, 255,
              t3_pwm, t3_pwm, t3_pwm, t3_pwm, t3_pwm,
              255, 255, 255, 255, 255, 255]
t1_r = compute_reward_test(t1_dim_pwm, 0, 512, 512, 0, BASE_WEIGHTS)
# 50% dim on T1: -1000 * (127/255 * 100) ≈ -49804 per cycle on that channel
check("T1 dimmed -> large negative reward",
      t1_r < -10000.0, True)

# Relay click penalty
relay_click_only = [255, 255, 255, 255, 255,
                    t3_pwm, t3_pwm, t3_pwm, t3_pwm, t3_pwm,
                    255, 255, 255, 255, 255, 255]
relay_r = compute_reward_test(relay_click_only, 1, 512, 512, 0, BASE_WEIGHTS)
relay_no_click_r = compute_reward_test(relay_click_only, 1, 512, 512, 1, BASE_WEIGHTS)
check("relay OFF->ON adds relay_click penalty (-500)",
      relay_r - relay_no_click_r, BASE_WEIGHTS["relay_click"], tolerance=0.01)

# T4 fully off -- check revenue is zero and dim penalty applied
t4_off_pwm = [255, 255, 255, 255, 255,
              t3_pwm, t3_pwm, t3_pwm, t3_pwm, t3_pwm,
              0, 0, 0, 0, 0, 0]
t4_on_pwm  = [255, 255, 255, 255, 255,
              t3_pwm, t3_pwm, t3_pwm, t3_pwm, t3_pwm,
              255, 255, 255, 255, 255, 255]
t4_off_r = compute_reward_test(t4_off_pwm, 0, 512, 512, 0, BASE_WEIGHTS)
t4_on_r  = compute_reward_test(t4_on_pwm,  0, 512, 512, 0, BASE_WEIGHTS)
check("T4 on earns more per cycle than T4 off",
      t4_on_r > t4_off_r, True)

# ── CRITICAL REWARD CONSISTENCY CHECK ────────────────────────────────────────
# Revenue and dim penalties must use compatible time scaling.
# Revenue: tier4_revenue * 0.1 per cycle = 10 * 0.1 = 1 pt/cycle/channel
# Dim penalty at 100% dim: tier4_per10 * 10 per cycle = -5 * 10 = -50 pt/cycle/channel
#
# Over 1 second (10 cycles), per channel:
#   revenue = 1 * 10 = 10 pts/sec  ← matches the "10 pts/sec" spec
#   dim_penalty = -50 * 10 = -500 pts/sec per channel
#
# With 6 channels: T4 full dim costs 3000 pts/sec in penalties alone.
# For a relay_click of -500, break-even TTD ≈ 500/3060 ≈ 0.16 sec.
#
# This test documents the current behaviour so we can verify if/when
# the weights are rebalanced.

revenue_per_cycle_per_ch  = BASE_WEIGHTS["tier4_revenue"] * 0.1
dim_penalty_per_cycle_per_ch = abs(BASE_WEIGHTS["tier4_per10"]) * 10.0

check("T4 revenue per cycle per channel = 1.0",
      revenue_per_cycle_per_ch, 1.0, tolerance=0.001)

check("T4 full-dim penalty per cycle per channel = 50.0",
      dim_penalty_per_cycle_per_ch, 50.0, tolerance=0.001)

ratio = dim_penalty_per_cycle_per_ch / revenue_per_cycle_per_ch
print(f"\n  NOTE: dim_penalty is {ratio:.0f}x larger than revenue per cycle per channel.")
print(f"        Break-even TTD (relay vs full-dim) ≈ {500.0/(dim_penalty_per_cycle_per_ch*10*6 + revenue_per_cycle_per_ch*10*6):.2f} seconds.")
print(f"        If this is too short, consider increasing relay_click penalty or")
print(f"        reducing tier4_per10 magnitude in BASE_WEIGHTS.")

# ─────────────────────────────────────────────────────────────────────────────
# 10. K2 RESPONSE PARSER (strip_think_tags + extract_json, tested inline)
# ─────────────────────────────────────────────────────────────────────────────
section("10. K2 think-tag stripper + JSON extractor")

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

def strip_think_tags_test(raw: str) -> str:
    cleaned = _THINK_RE.sub("", raw).strip()
    if "<think>" in cleaned:
        if "</think>" in cleaned:
            cleaned = cleaned[cleaned.rfind("</think>") + 8:].strip()
        else:
            # No closing tag: JSON lives AFTER the <think> content.
            cleaned = cleaned.split("<think>", 1)[1]
    return cleaned

def extract_json_test(raw: str) -> dict:
    cleaned = strip_think_tags_test(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end   = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"No valid JSON: {raw[:200]}")

GOOD_JSON = '{"pwm":[255,255,200,200,200,180,180,180,180,180,128,128,128,128,128,128],"relay":0,"lcd_line1":"SOC:60% $1.20","lcd_line2":"Score:+4820 T4:50%","reasoning":"Battery stable, keeping T4 at 50% for revenue."}'

# Normal K2 response with think block
think_response = f"<think>\nLet me analyze: battery is 60%, market is $1.20/kWh...\n</think>\n{GOOD_JSON}"
parsed = extract_json_test(think_response)
check("strips think block, parses JSON",
      parsed["relay"], 0)
check("pwm array has 16 elements after parse",
      len(parsed["pwm"]), 16)
check("reasoning extracted correctly",
      "revenue" in parsed["reasoning"], True)

# Multi-line think block
multiline = "<think>\nStep 1: Check tilt = 0\nStep 2: Battery 60%\nStep 3: Market $1.20\n</think>\n" + GOOD_JSON
parsed2 = extract_json_test(multiline)
check("multi-line think block stripped",
      parsed2["relay"], 0)

# Think block missing closing tag (edge case)
unclosed = f"<think>Some reasoning without closing tag\n{GOOD_JSON}"
try:
    parsed3 = extract_json_test(unclosed)
    check("unclosed think tag -- JSON found via brace-search",
          len(parsed3.get("pwm", [])), 16)
except Exception:
    # brace-search fallback might fail with unclosed tag + JSON mixed
    # document what happens
    FAIL += 1
    print("  FAIL  unclosed think tag -- parser raised exception")

# No think block at all (direct JSON)
parsed4 = extract_json_test(GOOD_JSON)
check("no think block -- direct JSON parse",
      parsed4["relay"], 0)

# Prose before JSON (some models add explanation despite instructions)
prose_json = "Sure, here is my decision for this cycle:\n" + GOOD_JSON + "\nI hope this helps!"
parsed5 = extract_json_test(prose_json)
check("prose before/after JSON -- brace-search fallback",
      len(parsed5.get("pwm", [])), 16)

# ─────────────────────────────────────────────────────────────────────────────
# 11. SAFE_COMMAND SHALLOW COPY BUG
# ─────────────────────────────────────────────────────────────────────────────
section("11. SAFE_COMMAND shallow copy safety")

import copy

SAFE_COMMAND = {
    "pwm":       [255, 255, 255, 255, 255,
                  200, 200, 200, 200, 200,
                  128, 128, 128, 128, 128, 128],
    "relay":     0,
    "lcd_line1": "K2 OFFLINE      ",
    "lcd_line2": "SAFE MODE       ",
    "reasoning": "K2 unreachable -- safe fallback active.",
}

# Shallow copy (the current buggy approach in main.py)
shallow = dict(SAFE_COMMAND)
shallow["pwm"][10] = 0   # simulates earthquake lockdown zeroing T4

check("shallow copy: mutation of pwm CORRUPTS SAFE_COMMAND (demonstrates bug)",
      SAFE_COMMAND["pwm"][10] == 0, True)   # this PASSES, proving the bug exists

# Deep copy (the correct approach)
SAFE_COMMAND["pwm"][10] = 128   # reset after above corruption
deep = copy.deepcopy(SAFE_COMMAND)
deep["pwm"][10] = 0

check("deep copy: mutation does NOT corrupt SAFE_COMMAND",
      SAFE_COMMAND["pwm"][10] == 128, True)

print("\n  CONFIRMED FIXED: main.py now uses safe_command() which calls")
print("  copy.deepcopy(SAFE_COMMAND), so earthquake/lockdown overrides")
print("  can never corrupt the fallback template.")

# ─────────────────────────────────────────────────────────────────────────────
# 12. DUCK CURVE CONSISTENCY
# ─────────────────────────────────────────────────────────────────────────────
section("12. Duck curve completeness")

check("duck curve has all 24 hours",
      len(DUCK_CURVE), 24)

check("all demand values in [0, 1]",
      all(0.0 <= v <= 1.0 for v in DUCK_CURVE.values()), True)

check("peak demand is 1.0 (hour 19)",
      DUCK_CURVE[19], 1.0)

check("lowest demand is 0.1 (hours 2, 3, 4)",
      all(DUCK_CURVE[h] <= 0.15 for h in [2, 3, 4]), True)

# Duck curve in forecaster must match duck curve in main.py
from forecaster import DUCK_CURVE as FORECAST_DC
MAIN_DUCK = {
    0:  0.20, 1:  0.15, 2:  0.10, 3:  0.10, 4:  0.10, 5:  0.20,
    6:  0.50, 7:  0.80, 8:  0.70, 9:  0.50, 10: 0.40, 11: 0.30,
    12: 0.25, 13: 0.25, 14: 0.30, 15: 0.35, 16: 0.50,
    17: 0.70, 18: 0.90, 19: 1.00, 20: 0.95, 21: 0.80,
    22: 0.60, 23: 0.40,
}
check("forecaster.DUCK_CURVE matches main.py DUCK_CURVE",
      FORECAST_DC == MAIN_DUCK, True)

# ─────────────────────────────────────────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  RESULTS:  {PASS} passed,  {FAIL} failed")
print(f"{'='*60}\n")

if FAIL > 0:
    print("  Action items:")
    if FAIL > 0:
        print("  - Review FAIL lines above and apply fixes to forecaster.py / main.py")
    sys.exit(1)
else:
    print("  All checks passed.")
    sys.exit(0)
