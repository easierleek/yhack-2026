# ============================================================
#  NEO — Nodal Energy Oracle
#  backend/main.py  —  AI Control Loop
#  YHack 2025
#
#  ROLE: AI / Backend Engineer (Turtle)
#
#  Core loop (runs every 100 ms):
#    1. Read sensor CSV from Arduino over USB serial
#    2. Update virtual battery + sensor history
#    3. Run forecaster — pre-compute predictive signals
#    4. Every 2 s: call K2 Think V2 to get a PWM/relay command
#    5. Apply hard safety overrides (T1, earthquake)
#    6. Compute reward score
#    7. Send command string back to Arduino
#    8. Push full state to dashboard
# ============================================================

import copy
import os
import re
import sys
import json
import math
import time
import threading
import serial
from openai import OpenAI
from dotenv import load_dotenv

# ── Load .env before anything else ────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── Path setup ────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

# ── NEW: Resilience & Monitoring Modules ──────────────────────────────────────
try:
    from logger import logger
    _LOGGER = True
except ImportError:
    _LOGGER = False
    logger = None

try:
    from sensor_manager import SensorManager
    _SENSOR_MGR = True
except ImportError:
    _SENSOR_MGR = False
    SensorManager = None

try:
    from k2_client import K2Client
    _K2_CLIENT = True
except ImportError:
    _K2_CLIENT = False
    K2Client = None

try:
    from decision_store import get_store as get_decision_store
    _DECISION_STORE = True
except ImportError:
    _DECISION_STORE = False
    get_decision_store = None

# ── Optional modules (system keeps running if any are missing) ─────────────────
try:
    from backend.eia_client import get_market_price, warm_cache, get_cache_status
except ImportError:
    try:
        from eia_client import get_market_price, warm_cache, get_cache_status
    except ImportError:
        get_market_price = None
        warm_cache       = None
        get_cache_status = None
        print("[WARN] eia_client.py not found — simulated market price active.")

try:
    from backend.forecaster import compute_forecast
except ImportError:
    try:
        from forecaster import compute_forecast
    except ImportError:
        compute_forecast = None
        print("[WARN] forecaster.py not found — forecast signals will be absent.")

try:
    from frontend.dashboard import run_dashboard, update_state as _dash_update
    _DASH = True
except ImportError:
    try:
        from dashboard import run_dashboard, update_state as _dash_update
        _DASH = True
    except ImportError:
        _DASH = False
        _dash_update = lambda _: None
        print("[WARN] dashboard.py not found — running headless.")

# Policy engine is an addon — silently disabled if not present
try:
    from backend.policy_engine import PolicyEngine
    _POLICY = True
except ImportError:
    try:
        from policy_engine import PolicyEngine
        _POLICY = True
    except ImportError:
        _POLICY = False

# ── Initialize Resilience Systems ──────────────────────────────────────────────
sensor_manager = None
k2_client = None
decision_store = None

if _SENSOR_MGR:
    try:
        sensor_manager = SensorManager()
    except Exception as e:
        if _LOGGER:
            logger.error(f"Failed to initialize SensorManager: {e}", event_type="init_error")
        _SENSOR_MGR = False

if _K2_CLIENT and K2_API_KEY:
    try:
        k2_client = K2Client(K2_API_KEY, K2_BASE_URL, K2_MODEL)
    except Exception as e:
        if _LOGGER:
            logger.error(f"Failed to initialize K2Client: {e}", event_type="init_error")
        _K2_CLIENT = False

if _DECISION_STORE:
    try:
        decision_store = get_decision_store()
    except Exception as e:
        if _LOGGER:
            logger.error(f"Failed to initialize DecisionStore: {e}", event_type="init_error")
        _DECISION_STORE = False

# ─── CONFIG (all values come from .env) ───────────────────────────────────────
SERIAL_PORT      = os.environ.get("NEO_SERIAL_PORT",  "COM3")
BAUD_RATE        = 9600
K2_API_KEY       = os.environ.get("K2_API_KEY",       "")
K2_BASE_URL      = "https://api.k2think.ai/v1"
K2_MODEL         = "MBZUAI-IFM/K2-Think-v2"
K2_CALL_INTERVAL = float(os.environ.get("K2_CALL_INTERVAL", "2.0"))
SIM_SPEED        = float(os.environ.get("SIM_SPEED",        "60"))
LOOP_MS          = 100   # target control loop period in milliseconds

# ─── SIMULATED CLOCK ──────────────────────────────────────────────────────────
SIM_START = time.time()

def get_sim_hour() -> float:
    return ((time.time() - SIM_START) * SIM_SPEED / 3600.0) % 24.0

# ─── DUCK CURVE ───────────────────────────────────────────────────────────────
DUCK_CURVE: dict[int, float] = {
     0: 0.20,  1: 0.15,  2: 0.10,  3: 0.10,  4: 0.10,  5: 0.20,
     6: 0.50,  7: 0.80,  8: 0.70,  9: 0.50, 10: 0.40, 11: 0.30,
    12: 0.25, 13: 0.25, 14: 0.30, 15: 0.35, 16: 0.50,
    17: 0.70, 18: 0.90, 19: 1.00, 20: 0.95, 21: 0.80,
    22: 0.60, 23: 0.40,
}

def get_duck_demand() -> float:
    return DUCK_CURVE[int(get_sim_hour()) % 24]

# ─── BASE PENALTY / REWARD WEIGHTS ────────────────────────────────────────────
# PolicyEngine applies modifiers on top of these at runtime when mayor
# policies are active.  Used directly when policy engine is disabled.
BASE_WEIGHTS: dict[str, float] = {
    "tier1_dim":     -1000.0,   # per 1% reduction — catastrophic
    "tier2_per10":     -50.0,   # per 10% dim below full
    "tier3_outrage":   -20.0,   # per 10% mismatch vs potentiometer demand
    "tier4_per10":      -5.0,   # per 10% dim (commercial — minor)
    "relay_click":    -500.0,   # every time relay switches ON
    "tier4_revenue":   +10.0,   # per second commercial LEDs are lit
}

# ─── VIRTUAL BATTERY ──────────────────────────────────────────────────────────
battery_soc          = 0.50   # starts at 50% charge
BATTERY_CAPACITY_MAH = 2000.0

# ─── Estimate solar and load from available sensors ──────────────────────────
def estimate_solar_and_load(light: int, temp_c: float, pressure_hpa: float, sim_hour: float) -> tuple[float, float]:
    """
    Since we only have light, temp, and pressure sensors:
    - Solar current (mA) estimated from light level
    - Load current (mA) estimated from time of day + weather + temperature
    """
    # Solar: 0-1023 LDR → 0-800 mA (brightness ∝ solar generation)
    solar_ma = (light / 1023.0) * 800.0
    
    # Load (base + temperature factor + time-of-day factor + pressure factor)
    base_load = 150.0  # Always some baseline load
    
    # Temperature load: hot days consume more (AC), cold days consume more (heating)
    temp_load = abs(temp_c - 20.0) * 5.0  # Peak at 20°C, +5mA per degree deviation
    
    # Time of day: peak usage 6-9am, 11am-1pm, 5-9pm
    if 6 <= sim_hour < 9:
        time_mult = 1.8
    elif 11 <= sim_hour < 13:
        time_mult = 1.6
    elif 17 <= sim_hour < 21:
        time_mult = 1.9
    elif 0 <= sim_hour < 5:
        time_mult = 0.4  # Night is low usage
    else:
        time_mult = 1.0
    
    # Pressure factor: dropping pressure = storm = people use more power (anxiety, lights, fans)
    # Assume base pressure is ~1013 hPa; lower = more demand
    pressure_load = max(0.0, (1013.0 - pressure_hpa) * 2.0)
    
    load_ma = base_load + temp_load + (base_load * time_mult) + pressure_load
    load_ma = max(50.0, load_ma)  # Never go below minimum load
    
    return solar_ma, load_ma

def update_battery(solar_ma: float, load_ma: float, dt: float) -> None:
    global battery_soc
    net_ma      = solar_ma - load_ma
    delta       = (net_ma * dt) / (BATTERY_CAPACITY_MAH * 3600.0)
    battery_soc = max(0.0, min(1.0, battery_soc + delta))

# ─── SENSOR HISTORY ───────────────────────────────────────────────────────────
history: list[dict] = []

def record_sensor(sensor: dict) -> None:
    history.append(sensor)
    if len(history) > 20:
        history.pop(0)

# ─── FALLBACK SLOPE (used only if forecaster.py is missing) ───────────────────
def _slope(key: str, window: int = 5) -> float:
    if len(history) < 2:
        return 0.0
    vals = [r[key] for r in history[-window:]]
    return (vals[-1] - vals[0]) / max(len(vals) - 1, 1)

# ─── FALLBACK MARKET PRICE (used only if eia_client.py is missing) ────────────
def _simulated_price(sim_hour: float) -> float:
    if   7  <= sim_hour < 9:   base = 2.5
    elif 18 <= sim_hour < 21:  base = 3.0
    elif 0  <= sim_hour < 5:   base = 0.5
    else:                       base = 1.0
    return round(max(0.5, min(3.0, base + math.sin(time.time() * 0.1) * 0.2)), 2)

def get_price(sim_hour: float) -> float:
    if get_market_price is not None:
        return get_market_price(sim_hour)
    return _simulated_price(sim_hour)

# ─── REWARD TRACKING ──────────────────────────────────────────────────────────
reward_score = 0.0

def compute_reward(
    pwm:        list[int],
    relay:      int,
    pot1:       int,
    pot2:       int,
    prev_relay: int,
    weights:    dict,
) -> float:
    global reward_score
    r = 0.0

    # T1 — hospitals
    for ch in [0, 1]:
        if pwm[ch] < 255:
            r += weights["tier1_dim"] * ((255 - pwm[ch]) / 255 * 100)

    # T2 — utilities
    for ch in [2, 3, 4]:
        r += weights["tier2_per10"] * ((255 - pwm[ch]) / 255.0 * 10.0)

    # T3 — residential: penalise mismatch vs potentiometer average
    pot_avg = ((pot1 + pot2) / 2.0) / 1023.0
    for ch in [5, 6, 7, 8, 9]:
        mismatch = abs(pwm[ch] / 255.0 - pot_avg)
        r += weights["tier3_outrage"] * (mismatch * 10.0)

    # T4 — commercial: revenue when on, penalty when dimmed
    for ch in [10, 11, 12, 13, 14, 15]:
        if pwm[ch] > 0:
            r += weights["tier4_revenue"] * 0.1          # per 100 ms cycle
        r += weights["tier4_per10"] * ((255 - pwm[ch]) / 255.0 * 10.0)

    # Relay click (OFF → ON transition only)
    if relay == 1 and prev_relay == 0:
        r += weights["relay_click"]

    reward_score += r
    return reward_score

# ─── K2 RESPONSE PARSER ───────────────────────────────────────────────────────
# K2 Think V2 is a reasoning model.  Every response starts with a
# <think>…</think> block before the actual JSON.  We must strip it.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

def strip_think_tags(raw: str) -> str:
    cleaned = _THINK_RE.sub("", raw).strip()
    if "<think>" in cleaned:
        if "</think>" in cleaned:
            cleaned = cleaned[cleaned.rfind("</think>") + 8:].strip()
        else:
            # No closing tag: JSON lives AFTER the <think> content.
            # Take everything after the opening tag so brace-search can find it.
            cleaned = cleaned.split("<think>", 1)[1]
    return cleaned

def extract_json(raw: str) -> dict:
    """
    Find and return the best JSON object in K2's response.

    K2 Think V2 reasons at length before outputting JSON.  We scan every
    { ... } block in the response and return the first one that:
      1. Parses as valid JSON, AND
      2. Contains a 'pwm' key with a list of exactly 16 integers.

    Falls back to any parseable JSON object if no pwm-bearing block is found.
    """
    cleaned = strip_think_tags(raw)

    # Collect every candidate substring that starts with { and ends with }
    candidates: list[str] = []

    # Walk every opening brace and find its matching closing brace
    depth = 0
    start = -1
    for i, ch in enumerate(cleaned):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                candidates.append(cleaned[start : i + 1])
                start = -1

    # Also try the whole stripped string as-is
    candidates.append(cleaned)

    best_fallback: dict | None = None

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue

        if not isinstance(obj, dict):
            continue

        # Ideal match: has pwm with exactly 16 integers
        pwm = obj.get("pwm")
        if (
            isinstance(pwm, list)
            and len(pwm) == 16
            and all(isinstance(v, int) for v in pwm)
        ):
            return obj

        # Keep as fallback if it has at least pwm and relay
        if best_fallback is None and "pwm" in obj and "relay" in obj:
            best_fallback = obj

    if best_fallback is not None:
        return best_fallback

    raise ValueError(f"No valid JSON found in K2 response:\n{raw[:500]}")

# ─── SAFE FALLBACK COMMAND ────────────────────────────────────────────────────
# Sent to Arduino whenever K2 is unreachable.
SAFE_COMMAND: dict = {
    "pwm":       [255, 255, 255, 255, 255,
                  200, 200, 200, 200, 200,
                  128, 128, 128, 128, 128, 128],
    "relay":     0,
    "lcd_line1": "K2 OFFLINE      ",
    "lcd_line2": "SAFE MODE       ",
    "reasoning": "K2 unreachable — safe fallback active.",
}

def safe_command() -> dict:
    """Always returns a deep copy so in-place PWM mutations never corrupt the template."""
    return copy.deepcopy(SAFE_COMMAND)

def repair_command(partial: dict) -> dict:
    """
    Patch a partially-valid K2 response so the control loop can still use it.

    Handles the most common failure mode: K2 reasons for so long that it runs
    out of generation budget mid-JSON, producing a truncated pwm array.

    Safe defaults applied per tier:
        CH 0-1   (T1 hospitals)  → 255  (always full, safety rule)
        CH 2-4   (T2 utilities)  → 255  (keep full when uncertain)
        CH 5-9   (T3 residential)→ 128  (half power — conservative)
        CH 10-15 (T4 commercial) → 128  (half power — conservative)
    """
    pwm = list(partial.get("pwm", []))

    # Pad to exactly 16 with tier-appropriate safe defaults
    safe_defaults = [255, 255, 255, 255, 255,       # T1, T2
                     128, 128, 128, 128, 128,         # T3
                     128, 128, 128, 128, 128, 128]    # T4
    while len(pwm) < 16:
        pwm.append(safe_defaults[len(pwm)])

    # Truncate if somehow over 16
    pwm = pwm[:16]

    # Always enforce T1 safety regardless of what K2 put there
    pwm[0] = 255
    pwm[1] = 255

    partial["pwm"] = pwm

    if not isinstance(partial.get("relay"), int) or partial["relay"] not in (0, 1):
        partial["relay"] = 0

    if not partial.get("lcd_line1"):
        partial["lcd_line1"] = "NEO REPAIRED    "

    if not partial.get("lcd_line2"):
        partial["lcd_line2"] = "PARTIAL RESPONSE"

    if not partial.get("reasoning"):
        partial["reasoning"] = "Partial K2 response repaired with safe defaults."

    return partial

# ─── SYSTEM PROMPT ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are NEO, the AI brain of a miniature smart city power grid on an Arduino.

YOUR ONLY JOB: read the JSON sensor data you receive and respond with a single
JSON object. No thinking out loud. No explanation. No prose. No lists. Nothing
before the opening brace. Nothing after the closing brace. JUST THE JSON.

=== POWER SOURCES ===
GREEN GRID : Solar (MB102). Cheap, limited. Tracked by LDR sensor.
STATE GRID : Utility adapter. Expensive. Activated by Relay.
Two INA219 sensors: solar_ma = solar output, load_ma = city draw.

=== 4 TIERS (16 PWM channels, 0=off, 255=full) ===
T1  CH 0-1   HOSPITALS   Always 255. Never dim. Catastrophic penalty if low.
T2  CH 2-4   UTILITIES   Industry demand (varies by temperature).
T3  CH 5-9   HOUSES      Residents demand (track potentiometer, but context matters).
T4  CH 10-15 MALLS       Commercial — can be dimmed for reserve charging.

=== HOW THE REWARD SYSTEM WORKS ===
Your goal is to minimize penalties:
  • dim T1 → CATASTROPHIC penalty (-1000/1% reduction)
  • dim T2 → HIGH penalty (-50 per 10%)
  • T3 mismatch from pot → PENALTY (-20 per 10% mismatch)
  • relay click → EXPENSIVE (-500 per activation)
  • dim T4 → small penalty (-5 per 10%)

You GAIN points by:
  • T4 revenue: +10/sec when T4 is on

When battery SOC will hit 0%, a relay click becomes inevitable unless you
pre-charge by dimming now. Your job: decide if it's cheaper to dim T4 early
(lose revenue) or click the relay late (catastrophic penalty).

=== WEATHER SIGNALS YOU RECEIVE ===

storm_probability (0.0 – 1.0)
  • Comes from: falling air pressure + dimming light
  • Meaning: clouds/storm approaching → solar about to drop →  battery vulnerable
  • K2's reasoning: if storm hits while battery is half-full, you're fine
    but if battery is nearly empty when storm hits, you fail. Pre-charge now?

solar_time_remaining (0–99999 seconds)
  • Meaning: how long until light hits zero (sun setting, major cloud cover)
  • If < 60 sec: solar will be GONE SOON
  • K2's reasoning: if solar dies in 30 seconds and you keep T4 bright,
    city load will drain battery in minutes. Should you dim T4 now to build buffer?

ttd_seconds (time to deficit)
  • How many seconds until battery SoC hits 0% at current drain rate
  • If < 10 sec: CRISIS NOW (dim everything except T1 or relay must activate)
  • If > 120 sec: probably safe (solar is strong, load is light)

t2_demand_factor (1.0 – 1.5)
  • Heat/cold multiplier: extreme temps = higher industry cooling/heating load
  • temp > 35°C → 1.50   (extreme heat, AC load spikes)
  • temp < 5°C  → 1.50   (extreme cold, heating load spikes)
  • K2's reasoning: if T2 normally draws 100 mA, at 1.50× it draws 150 mA.
    That's 50% more drain on battery. Does this change your power strategy?

mins_to_demand_spike (0–9999 minutes)
  • Duck curve prediction: when will residential demand surge?
  • Typical pattern: early morning (7–9am) and evening (6–9pm) are peaks
  • K2's reasoning: if spike arrives in 5 minutes and battery is at 30%,
    should you pre-dim T4 to build buffer before spike hits?

market_penalty_active (true/false)
  • Electricity price > $2/kWh — relay is EXTREMELY expensive to activate
  • K2's reasoning: normally relay costs 500 pts, but if market is spiking,
    maybe avoid relay at almost any cost. Dim T4 hard even if battery is OK?

breakeven_ttd
  • Economic threshold: TTD must be below this for dimming to be cheaper than relay
  • Calculated from: relay penalty cost vs. cost of holding T4 dimmed

=== ADVANCED STATISTICAL FEATURES (NEW) ===
You now receive rich statistical context about sensors:

Volatility (sensor_volatility metrics)
  • Measures: standard deviation of readings over last 15 samples
  • light_volatility = unstable light sensor (flickering clouds)
  • pressure_volatility = unstable pressure (turbulent weather)
  • battery_volatility = erratic charging (solar flickering)
  • K2's reasoning: high volatility in pressure + light suggests mixed weather

Momentum (sensor_momentum metrics)
  • Measures: rate of change (current_value - past_value) / time
  • light_momentum: negative = setting/approaching clouds, positive = clearing
  • pressure_momentum: negative = falling pressure (storm), positive = rising
  • battery_momentum: negative = draining faster, positive = charging well
  • K2's reasoning: if pressure_momentum < -0.05, aggressive storm incoming

Acceleration (sensor_acceleration metrics)
  • Measures: change in momentum (2nd derivative)
  • positive accel = trend strengthening, negative = trend weakening
  • pressure_acceleration < -0.0001 = storm pressure intensifying
  • light_acceleration = light disappearing rate changing
  • K2's reasoning: accelerating cloud movement = higher immediate risk

Percentile ranks (sensor_percentile metrics)
  • Ranks: where does current reading fall vs. historical distribution?
  • light_percentile = 0 (dark, night), 100 (bright, noon)
  • pressure_percentile = historical ranking
  • K2's reasoning: if light_percentile drops 80→20 in 3 min, solar crash coming

Trend strength (sensor_trend_strength)
  • Measures: how consistent is the trend direction?
  • 1.0 = perfectly consistent up or down trend
  • 0.0 = oscillating (no clear trend)
  • K2's reasoning: high trend strength in pressure = lock-in weather pattern

=== MONTE CARLO SCENARIOS (NEW) ===
You now receive probabilistic futures instead of just single points:

scenarios_count (integer)
  • How many plausible outcomes are being considered (typically 3-5)

dominant_scenario (string)
  • Name of most likely scenario: "Clear Skies", "Partial Storm", "Severe Storm", "Demand Spike"

dominant_probability (0.0 – 1.0)
  • How likely is the dominant scenario? 0.7 = 70% likely

expected_battery_5m_percent (float)
  • Probability-weighted prediction: what will battery be in 5 minutes?
  • Average across all scenarios weighted by their likelihood
  • K2's reasoning: "If I keep current power, expected battery = 32% in 5min"

relay_probability (0.0 – 1.0)
  • What's the probability relay will be *necessary* in next 5 min across scenarios?
  • 0.1 = low risk, 0.8 = relay likely needed soon
  • K2's reasoning: "High relay_probability means I should dim T4 *now* as insurance"

scenario_recommendation (string)
  • English recommendation from the dominant scenario
  • Examples: "Keep T4 normal; harvest solar", "Dim T4 to 40%; prepare relay"

K2's Bayesian reasoning:
  If you see: dominant_scenario="Severe Storm", relay_probability=0.85, expected_battery_5m=15%
  You should: Dim T4 immediately, prepare for relay, maybe activate now to pre-charge T1/T2.

  If you see: dominant_scenario="Clear Skies", relay_probability=0.05, expected_battery_5m=60%
  You should: Keep T4 bright, revenue is safe, solar will keep charging.

=== YOUR ACTUAL JOB: OPTIMIZE POWER GIVEN THESE RICH SIGNALS ===

You MUST do this reasoning every cycle (it's the ML part):

1. Check the dominant scenario AND relay_probability
   → If relay_probability > 0.6 AND expected_battery < 25%: Act NOW
   → Pre-dim T4 or activate relay to secure T1/T2

2. Analyze volatility + momentum + acceleration
   → High pressure volatility + negative pressure momentum + negative accel?
   → Storm is turbulent and intensifying. Pre-charge aggressively.
   → High light volatility + negative light momentum?
   → Partial cloud cover; solar is unstable. Build battery buffer.

3. Look at percentile ranks
   → Is battery_soc percentile dropping? (e.g., 60th → 20th)
   → System is entering crisis state faster than historical baseline.

4. Weigh the triplet: scenario + physics + economic signals
   → "Severe Storm (80% prob), pressure accelerating, relay cost $0.15/kWh"
   → → Relay is so expensive, I must avoid it: dim T4 to 20% to pre-charge.

5. Balance short-term (5-min scenario) vs. long-term (ttd_seconds)
   → If expected_battery_5m=40% but ttd=7200s (2h safe):
   → → No urgency; keep T4 bright unless market spiking.

=== YOUR RESPONSE MUST BE EXACTLY THIS JSON STRUCTURE ===
{"pwm":[255,255,X,X,X,X,X,X,X,X,X,X,X,X,X,X],"relay":0,"lcd_line1":"SOC:XX% $X.XX","lcd_line2":"Score:XXXXX T4:XX%","reasoning":"brief explanation"}

Rules:
- pwm: exactly 16 integers each 0-255
- relay: 0 or 1
- lcd_line1, lcd_line2: ≤16 chars
- reasoning: one short sentence (mention weather if reasoning about it)

DO NOT write anything before { or after }. Output the JSON and nothing else.
"""

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main() -> None:
    global battery_soc, reward_score

    # ── Startup logging ───────────────────────────────────────────────────────
    if _LOGGER:
        logger.log_startup({
            "serial_port": SERIAL_PORT,
            "k2_available": bool(K2_API_KEY and _K2_CLIENT),
            "forecaster_available": compute_forecast is not None,
            "dashboard_available": _DASH,
            "policy_available": _POLICY,
            "sensor_manager_available": _SENSOR_MGR,
            "decision_store_available": _DECISION_STORE,
        })
    
    # ── EIA cache warm-up ──────────────────────────────────────────────────────
    if warm_cache is not None:
        try:
            warm_cache()
        except Exception as e:
            print(f"[EIA] Warm-up failed (simulated price active): {e}")

    # ── Dashboard thread ───────────────────────────────────────────────────────
    if _DASH:
        threading.Thread(target=run_dashboard, daemon=True).start()
        print("[NEO] Dashboard started.")

    # ── Policy engine (addon — silently skipped if unavailable) ───────────────
    policy = PolicyEngine(sim_start=SIM_START, sim_speed=SIM_SPEED) if _POLICY else None

    # ── K2 client already initialized above ────────────────────────────────────
    if not K2_API_KEY:
        print("[WARN] K2_API_KEY is not set in .env — AI will use K2 fallback.")

    # ── Serial connection ──────────────────────────────────────────────────────
    print(f"[NEO] Opening serial port {SERIAL_PORT} @ {BAUD_RATE} baud...")
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    except serial.SerialException as e:
        print(f"[FATAL] Cannot open serial port: {e}")
        print("        → Check NEO_SERIAL_PORT in your .env file.")
        sys.exit(1)
    time.sleep(2)   # wait for Arduino bootloader reset
    print("[NEO] Serial connected. Starting control loop...\n")

    # ── Loop state ─────────────────────────────────────────────────────────────
    prev_relay       = 0
    last_time        = time.time()
    last_k2_call     = 0.0
    command: dict    = safe_command()
    k2_calls         = 0
    last_btn_seen    = 0

    # ── Control loop ──────────────────────────────────────────────────────────
    while True:
        loop_start = time.time()

        # ── 1. Read sensor CSV from Arduino ───────────────────────────────────
        try:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue
            parts = line.split(",")
            # Only 3 sensors: light, temp_c, pressure_hpa (+ optional button)
            if len(parts) < 3:
                continue
            sensor: dict = {
                "light":        int(parts[0]),
                "temp_c":       float(parts[1]),
                "pressure_hpa": float(parts[2]),
                "button":       int(parts[3]) if len(parts) > 3 else 0,
            }
            
            # ── Sensor validation ─────────────────────────────────────────────
            if sensor_manager:
                for sensor_key in ["light", "temp_c", "pressure_hpa"]:
                    result = sensor_manager.update_reading(
                        f"{sensor_key}_lux" if sensor_key == "light" else 
                        f"{sensor_key}_c" if sensor_key == "temp_c" else
                        f"{sensor_key}_hpa",
                        sensor[sensor_key]
                    )
                    if result["warnings"]:
                        for warning in result["warnings"]:
                            if _LOGGER:
                                logger.log_sensor_anomaly(sensor_key, sensor[sensor_key], sensor_manager.last_readings.get(sensor_key), warning)
        
        except (ValueError, IndexError) as e:
            print(f"[SERIAL] Parse error ({e}): {line!r}")
            if _LOGGER:
                logger.error(f"[SERIAL] Parse error: {e}", event_type="serial_error")
            continue

        # ── 2. Update battery and history ─────────────────────────────────────
        now       = time.time()
        dt        = now - last_time
        last_time = now

        record_sensor(sensor)
        sim_hour = get_sim_hour()
        
        # Estimate solar and load from available sensors (light, temp, pressure)
        solar_ma, load_ma = estimate_solar_and_load(sensor["light"], sensor["temp_c"], sensor["pressure_hpa"], sim_hour)
        sensor["solar_ma"] = solar_ma
        sensor["load_ma"] = load_ma
        
        update_battery(solar_ma, load_ma, dt)
        
        price    = get_price(sim_hour)

        # ── 3. Policy engine (addon) ───────────────────────────────────────────
        btn = sensor["button"]
        if policy is not None and btn != 0 and btn != last_btn_seen:
            name = policy.press(btn)
            if name:
                print(f"[MAYOR] {name}")
        last_btn_seen = btn

        weights       = policy.get_weights()        if policy else dict(BASE_WEIGHTS)
        policy_tweaks = policy.get_context_tweaks() if policy else {}
        policy_status = policy.status_dict()        if policy else {"active_policy": "None", "active_policies": [], "policy_expires_in": 0.0}

        # Solar Subsidy: boost SoC seen by forecaster and K2
        effective_soc = battery_soc
        if policy_tweaks.get("policy_solar_subsidy"):
            effective_soc = min(1.0, battery_soc + policy_tweaks.get("soc_bonus", 0.20))

        # ── 4. Run forecaster ─────────────────────────────────────────────────
        if compute_forecast is not None:
            forecast = compute_forecast(
                history         = history,
                battery_soc     = effective_soc,
                solar_ma        = sensor["solar_ma"],
                load_ma         = sensor["load_ma"],
                temp_c          = sensor["temp_c"],
                sim_hour        = sim_hour,
                market_price    = price,
                penalty_weights = weights,
            )
        else:
            forecast = {
                "sun_slope":             round(_slope("light"),        2),
                "pressure_slope":        round(_slope("pressure_hpa"), 4),
                "ttd_seconds":           99999.0,
                "storm_probability":     0.0,
                "solar_time_remaining":  99999.0,
                "mins_to_demand_spike":  9999.0,
                "t2_demand_factor":      1.0,
                "dim_t4_recommended":    False,
                "breakeven_ttd":         0.0,
                "market_penalty_active": price > 2.0,
            }

        # ── 5. Build K2 context ────────────────────────────────────────────────
        context: dict = {
            **sensor,
            "battery_soc":  round(effective_soc, 3),
            "sim_hour":     round(sim_hour, 2),
            "duck_demand":  round(get_duck_demand(), 2),
            "relay_state":  prev_relay,
            "market_price": price,
            "reward_score": round(reward_score, 1),
            **forecast,
            # Inject active policy flags so K2 knows what the mayor did
            **{k: v for k, v in policy_tweaks.items() if k != "soc_bonus"},
        }

        # ── 6. Call K2 Think V2 (rate-limited to K2_CALL_INTERVAL) ───────────
        was_cached = False
        if now - last_k2_call >= K2_CALL_INTERVAL and (K2_API_KEY or k2_client):
            last_k2_call = now
            k2_calls    += 1
            try:
                # Use resilient K2 client if available
                if k2_client:
                    response = k2_client.call(SYSTEM_PROMPT, context)
                    was_cached = response.cached
                    
                    if response.success or response.cached:
                        command = {
                            "pwm": response.pwm,
                            "relay": response.relay,
                            "lcd_line1": response.lcd_text[:16] if response.lcd_text else "NEO ACTIVE",
                            "lcd_line2": f"Score:{reward_score:.0f}",
                            "reasoning": response.raw_response[:80] if response.raw_response else "K2 response",
                        }
                        if response.error:
                            if _LOGGER:
                                logger.log_k2_error(response.error, 0, k2_client.circuit_breaker.state == "open")
                    else:
                        command = safe_command()
                        if _LOGGER:
                            logger.log_k2_error(response.error or "Unknown error", 1, False)
                else:
                    # Fallback to old OpenAI approach if k2_client not available
                    from openai import OpenAI
                    k2 = OpenAI(api_key=K2_API_KEY or "placeholder", base_url=K2_BASE_URL)
                    resp = k2.chat.completions.create(
                        model       = K2_MODEL,
                        max_tokens  = 8192,
                        temperature = 0.1,
                        messages    = [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user",   "content": json.dumps(context)},
                        ],
                    )
                    raw     = resp.choices[0].message.content or ""
                    command = extract_json(raw)

                    if len(command.get("pwm", [])) != 16:
                        command = repair_command(command)
                        print(f"[K2 #{k2_calls}] Repaired partial response (pwm padded to 16)")

                # Hard safety: hospitals always full power
                command["pwm"][0] = 255
                command["pwm"][1] = 255

                reasoning_text = command.get('reasoning', '')
                if len(reasoning_text) > 60:
                    print(f"[K2 #{k2_calls}] {reasoning_text[:60]}...")
                else:
                    print(f"[K2 #{k2_calls}] {reasoning_text}")

            except Exception as e:
                print(f"[K2 ERROR] {e}")
                if _LOGGER:
                    logger.error(f"K2 call failed: {str(e)}", event_type="k2_error")
                command = safe_command()

        # ── 7. Hard overrides (enforced in Python, not just in the prompt) ────

        # Commercial Lockdown policy: zero T4 regardless of K2
        if policy is not None and policy.commercial_lockdown_active():
            for ch in range(10, 16):
                command["pwm"][ch] = 0

        # Earthquake: override everything — tilt sensor is law
        if sensor["tilt"] == 1:
            command["pwm"][:2]  = [255, 255]   # T1 hospitals full
            command["pwm"][2:5] = [255, 255, 255]   # T2 utilities full
            command["pwm"][5:10] = [128] * 5    # T3 residential half
            command["pwm"][10:16] = [0] * 6     # T4 commercial off
            command["relay"]     = 1
            command["lcd_line1"] = "SEISMIC LOCKDOWN"
            command["lcd_line2"] = "ALL CLEAR NEEDED"
            command["reasoning"] = "Earthquake lockdown — tilt sensor fired."

        # ── 8. Compute reward ─────────────────────────────────────────────────
        reward_score = compute_reward(
            pwm        = command["pwm"],
            relay      = command["relay"],
            pot1       = sensor["pot1"],
            pot2       = sensor["pot2"],
            prev_relay = prev_relay,
            weights    = weights,
        )
        
        # ── Log decision to store ──────────────────────────────────────────────
        if decision_store and now - last_k2_call < 0.5:  # Only log recent K2 decisions
            try:
                decision_store.log_decision(
                    context=context,
                    k2_response=type('obj', (object,), {'pwm': command["pwm"], 'relay': command["relay"], 'raw_response': command.get("reasoning", "")}),
                    reward_score=reward_score,
                    was_cached=was_cached,
                    error_occurred=False,
                )
            except Exception as e:
                if _LOGGER:
                    logger.error(f"Failed to log decision: {str(e)}", event_type="store_error")
        
        # ── Log reward ─────────────────────────────────────────────────────────
        if _LOGGER:
            penalties = {
                "t1": weights["tier1_dim"],
                "t2": weights["tier2_per10"],
                "t3": weights["tier3_outrage"],
                "t4": weights["tier4_per10"],
            }
            tier_breakdown = {
                "t1_pwm": command["pwm"][0],
                "t2_pwm_avg": sum(command["pwm"][2:5]) / 3,
                "t3_pwm_avg": sum(command["pwm"][5:10]) / 5,
                "t4_pwm_avg": sum(command["pwm"][10:16]) / 6,
            }
            logger.log_reward_score(reward_score, penalties, tier_breakdown)
        
        prev_relay = command["relay"]

        # ── 9. Grid fault detection ───────────────────────────────────────────
        # If T4 was commanded off but measured load didn't drop, flag it.
        fault_msg = ""
        if len(history) >= 4:
            prev_load = history[-4]["load_ma"]
            this_load = sensor["load_ma"]
            t4_avg    = sum(command["pwm"][10:16]) / 6.0
            if t4_avg < 30 and abs(this_load - prev_load) < 5.0 and prev_load > 50:
                fault_msg = f"Grid Fault: T4 dim, load unchanged ({this_load:.0f} mA)"
                print(f"[FAULT] {fault_msg}")

        # ── 10. Send command to Arduino ───────────────────────────────────────
        pwm_str  = ",".join(str(v) for v in command["pwm"])
        lcd1     = command.get("lcd_line1", "NEO RUNNING     ")[:16].ljust(16)
        lcd2     = command.get("lcd_line2", "                ")[:16].ljust(16)
        out      = f"PWM:{pwm_str},RELAY:{command['relay']},LCD1:{lcd1},LCD2:{lcd2}\n"
        try:
            ser.write(out.encode("utf-8"))
        except serial.SerialException as e:
            print(f"[SERIAL] Write error: {e}")

        # ── 11. Push state to dashboard ───────────────────────────────────────
        eia_status: dict = {}
        if get_cache_status is not None:
            try:
                eia_status = get_cache_status()
            except Exception:
                pass

        loop_ms = (time.time() - loop_start) * 1000.0
        
        # ── Log loop timing ────────────────────────────────────────────────────
        if _LOGGER:
            logger.log_loop_timing(loop_ms, now - last_k2_call >= K2_CALL_INTERVAL, [loop_ms])

        _dash_update({
            "battery_soc":          battery_soc,
            "sim_hour":             sim_hour,
            "market_price":         price,
            "relay":                command["relay"],
            "reward_score":         reward_score,
            "light":                sensor["light"],
            "temp_c":               sensor["temp_c"],
            "pressure_hpa":         sensor["pressure_hpa"],
            "solar_ma":             sensor["solar_ma"],
            "load_ma":              sensor["load_ma"],
            "pot1":                 sensor["pot1"],
            "pot2":                 sensor["pot2"],
            "tilt":                 sensor["tilt"],
            "button":               sensor["button"],
            "sun_slope":            forecast.get("sun_slope",            0.0),
            "pressure_slope":       forecast.get("pressure_slope",       0.0),
            "duck_demand":          get_duck_demand(),
            "storm_probability":    forecast.get("storm_probability",    0.0),
            "ttd_seconds":          forecast.get("ttd_seconds",          99999.0),
            "dim_t4_recommended":   forecast.get("dim_t4_recommended",   False),
            "recommended_t4_pwm":   forecast.get("recommended_t4_pwm",   255),
            "mins_to_demand_spike": forecast.get("mins_to_demand_spike", 9999.0),
            "pwm":                  command["pwm"],
            "reasoning":            command.get("reasoning", ""),
            "eia_retail":           eia_status.get("retail_usd_per_kwh", 0.17),
            "eia_demand_mw":        eia_status.get("demand_mw",          400_000.0),
            "eia_live":             eia_status.get("live",               False),
            "eia_age_s":            eia_status.get("age_seconds",        0.0),
            "fault":                fault_msg,
            "loop_ms":              loop_ms,
            "k2_calls":             k2_calls,
            **policy_status,
        })

        # ── 12. Pace to 100 ms ────────────────────────────────────────────────
        elapsed = time.time() - loop_start
        time.sleep(max(0.0, LOOP_MS / 1000.0 - elapsed))


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  NEO — Nodal Energy Oracle  |  YHack 2025")
    print("  Enhanced with Resilience & Monitoring")
    print("=" * 60)
    print(f"  Serial port   : {SERIAL_PORT}")
    print(f"  K2 model      : {K2_MODEL}")
    print(f"  K2 interval   : {K2_CALL_INTERVAL}s")
    print(f"  Sim speed     : {SIM_SPEED}x")
    print(f"  EIA client    : {'enabled' if get_market_price  else 'SIMULATED'}")
    print(f"  Forecaster    : {'enabled' if compute_forecast  else 'DISABLED'}")
    print(f"  Policy engine : {'enabled' if _POLICY          else 'addon not loaded'}")
    print(f"  Dashboard     : {'enabled' if _DASH            else 'headless'}")
    print(f"  Logger        : {'enabled' if _LOGGER          else 'disabled'}")
    print(f"  Sensor mgr    : {'enabled' if _SENSOR_MGR      else 'disabled'}")
    print(f"  K2 resilience : {'enabled (circuit breaker)' if _K2_CLIENT else 'disabled'}")
    print(f"  Decision store: {'enabled (SQLite)' if _DECISION_STORE else 'disabled'}")
    print("=" * 60 + "\n")
    try:
        main()
    except KeyboardInterrupt:
        if _LOGGER:
            logger.log_shutdown("Keyboard interrupt", time.time() - SIM_START)
        print("\n[SHUTDOWN] NEO system halted.")
        if decision_store:
            summary = decision_store.get_summary()
            print(f"\n[SUMMARY] {summary['total_decisions']} decisions logged")
            print(f"          Avg reward: {summary['avg_reward']:.1f}")
            print(f"          Cache rate: {summary['cache_rate']*100:.1f}%")
            print(f"          Error rate: {summary['error_rate']*100:.1f}%")
            decision_store.close()
    except Exception as e:
        if _LOGGER:
            logger.error(f"Fatal error: {str(e)}", event_type="fatal_error")
        raise
