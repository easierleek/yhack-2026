# ============================================================
#  NEO — Nodal Energy Oracle
#  backend/main.py  —  AI Control Loop
#  YHack 2025
#
#  ROLE: AI / Backend Engineer (Turtle) owns this file.
#
#  Responsibilities
#  ─────────────────
#  - 100 ms serial loop: read Arduino CSV → send command string
#  - Call K2 Think V2 every 2 s for grid decisions
#  - Strip <think>…</think> reasoning blocks from K2 response
#  - Run forecaster.py every cycle to pre-compute predictive signals
#  - Run policy_engine.py to track mayor button presses + weight mods
#  - Integrate EIA live market price via eia_client.py
#  - Push live state to terminal dashboard via frontend/dashboard.py
#  - Maintain virtual battery, duck curve, reward score
#
#  Serial protocol  (must match neo_arduino.ino exactly)
#    RX from Arduino (100 ms):
#      "light,temp_c,pressure_hpa,solar_ma,load_ma,pot1,pot2,tilt,button\n"
#    TX to Arduino (after each K2 decision):
#      "PWM:v0,...,v15,RELAY:r,LCD1:line1,LCD2:line2\n"
#
#  Environment variables (set before running)
#    NEO_SERIAL_PORT   default COM3  (Mac/Linux: /dev/tty.usbmodemXXXX)
#    K2_API_KEY        your K2 Think V2 bearer token
#    EIA_API_KEY       your EIA API key
# ============================================================

import os
import re
import sys
import json
import math
import time
import threading
import serial

from openai import OpenAI

# ── Path setup so we can import from project root ─────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

# ── EIA client (optional — falls back to simulation if missing) ───────────────
try:
    from backend.eia_client import get_market_price, warm_cache, get_cache_status
    _EIA_AVAILABLE = True
except ImportError:
    try:
        from eia_client import get_market_price, warm_cache, get_cache_status
        _EIA_AVAILABLE = True
    except ImportError:
        _EIA_AVAILABLE = False
        print("[WARN] eia_client.py not found — using simulated market price.")

# ── Dashboard (optional — falls back to headless if missing) ──────────────────
try:
    from frontend.dashboard import run_dashboard, update_state as dash_update
    _DASH_AVAILABLE = True
except ImportError:
    try:
        from dashboard import run_dashboard, update_state as dash_update
        _DASH_AVAILABLE = True
    except ImportError:
        _DASH_AVAILABLE = False
        dash_update = lambda _: None
        print("[WARN] dashboard.py not found — running headless.")

# ── Forecaster ────────────────────────────────────────────────────────────────
try:
    from backend.forecaster import compute_forecast
    _FORECAST_AVAILABLE = True
except ImportError:
    try:
        from forecaster import compute_forecast
        _FORECAST_AVAILABLE = True
    except ImportError:
        _FORECAST_AVAILABLE = False
        print("[WARN] forecaster.py not found — forecast signals will be absent from K2 context.")

# ── Policy engine ─────────────────────────────────────────────────────────────
try:
    from backend.policy_engine import PolicyEngine
    _POLICY_AVAILABLE = True
except ImportError:
    try:
        from policy_engine import PolicyEngine
        _POLICY_AVAILABLE = True
    except ImportError:
        _POLICY_AVAILABLE = False
        print("[WARN] policy_engine.py not found — mayor policies disabled.")

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
SERIAL_PORT       = os.environ.get("NEO_SERIAL_PORT", "COM3")
BAUD_RATE         = 9600

K2_API_KEY        = os.environ.get("K2_API_KEY",  "YOUR_K2_KEY_HERE")
K2_BASE_URL       = "https://api.k2think.ai/v1"
K2_MODEL          = "MBZUAI-IFM/K2-Think-v2"   # exact model ID — do not change

K2_CALL_INTERVAL  = 2.0    # seconds between K2 API calls (API budget management)
LOOP_INTERVAL_MS  = 100    # target control loop period in ms

# ─── SIMULATED CLOCK ──────────────────────────────────────────────────────────
SIM_START = time.time()
SIM_SPEED = 60   # 1 real second = 60 simulated seconds → 1 real minute = 1 sim hour

def get_sim_hour() -> float:
    return ((time.time() - SIM_START) * SIM_SPEED / 3600.0) % 24.0

# ─── DUCK CURVE ───────────────────────────────────────────────────────────────
DUCK_CURVE: dict[int, float] = {
    0:  0.20, 1:  0.15, 2:  0.10, 3:  0.10, 4:  0.10, 5:  0.20,
    6:  0.50, 7:  0.80, 8:  0.70, 9:  0.50, 10: 0.40, 11: 0.30,
    12: 0.25, 13: 0.25, 14: 0.30, 15: 0.35, 16: 0.50,
    17: 0.70, 18: 0.90, 19: 1.00, 20: 0.95, 21: 0.80,
    22: 0.60, 23: 0.40,
}

def get_duck_demand() -> float:
    return DUCK_CURVE[int(get_sim_hour()) % 24]

# ─── BASE PENALTY / REWARD WEIGHTS ────────────────────────────────────────────
# PolicyEngine applies modifier functions on top of these at runtime.
BASE_PENALTY_WEIGHTS: dict[str, float] = {
    "tier1_dim":     -1000.0,
    "tier2_per10":   -50.0,
    "tier3_outrage": -20.0,
    "tier4_per10":   -5.0,
    "relay_click":   -500.0,
    "tier4_revenue": +10.0,
}

# ─── FALLBACK MARKET PRICE ────────────────────────────────────────────────────
def _simulated_market_price(sim_hour: float) -> float:
    """Used only when eia_client is unavailable."""
    if   7  <= sim_hour < 9:   base = 2.5
    elif 18 <= sim_hour < 21:  base = 3.0
    elif 0  <= sim_hour < 5:   base = 0.5
    else:                       base = 1.0
    noise = math.sin(time.time() * 0.1) * 0.2
    return round(max(0.5, min(3.0, base + noise)), 2)

def get_price(sim_hour: float) -> float:
    if _EIA_AVAILABLE:
        return get_market_price(sim_hour)
    return _simulated_market_price(sim_hour)

# ─── VIRTUAL BATTERY ──────────────────────────────────────────────────────────
battery_soc           = 0.50
BATTERY_CAPACITY_MAH  = 2000.0

def update_battery(solar_ma: float, load_ma: float, dt: float) -> None:
    global battery_soc
    net_ma = solar_ma - load_ma
    delta  = (net_ma * dt) / (BATTERY_CAPACITY_MAH * 3600.0)
    battery_soc = max(0.0, min(1.0, battery_soc + delta))

# ─── SENSOR HISTORY ───────────────────────────────────────────────────────────
history: list[dict] = []

def record_sensor(sensor: dict) -> None:
    history.append(sensor)
    if len(history) > 20:
        history.pop(0)

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
    """
    Computes the incremental reward for this control cycle and adds it to
    the running total.  Uses the weights returned by PolicyEngine.get_weights()
    so that active mayor policies are reflected in the score.
    """
    global reward_score
    r = 0.0

    # Tier 1 — hospitals must always be 255
    for ch in [0, 1]:
        if pwm[ch] < 255:
            reduction_pct = (255 - pwm[ch]) / 255 * 100
            r += weights["tier1_dim"] * reduction_pct

    # Tier 2 — utilities
    for ch in [2, 3, 4]:
        dim_pct = (255 - pwm[ch]) / 255.0
        r += weights["tier2_per10"] * (dim_pct * 10.0)

    # Tier 3 — residential: penalise mismatch vs potentiometer average
    pot_avg = ((pot1 + pot2) / 2.0) / 1023.0
    for ch in [5, 6, 7, 8, 9]:
        actual   = pwm[ch] / 255.0
        mismatch = abs(actual - pot_avg)
        r += weights["tier3_outrage"] * (mismatch * 10.0)

    # Tier 4 — commercial: revenue + dim penalty
    for ch in [10, 11, 12, 13, 14, 15]:
        if pwm[ch] > 0:
            r += weights["tier4_revenue"] * 0.1   # per 100 ms cycle
        dim_pct = (255 - pwm[ch]) / 255.0
        r += weights["tier4_per10"] * (dim_pct * 10.0)

    # Relay click penalty (only on OFF → ON transition)
    if relay == 1 and prev_relay == 0:
        r += weights["relay_click"]

    reward_score += r
    return reward_score

# ─── K2 RESPONSE PARSER ───────────────────────────────────────────────────────
# K2 Think V2 is a reasoning model. It always prefixes its response with a
# <think>…</think> block before outputting the actual JSON.
# strip_think_tags() removes that block so json.loads() doesn't crash.

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

def strip_think_tags(raw: str) -> str:
    """Remove K2's <think>…</think> reasoning block from the response."""
    cleaned = _THINK_RE.sub("", raw).strip()
    # Handle models that emit <think> without a closing tag
    if "<think>" in cleaned:
        if "</think>" in cleaned:
            cleaned = cleaned[cleaned.rfind("</think>") + 8:].strip()
        else:
            cleaned = cleaned.split("<think>")[0].strip()
    return cleaned

def extract_json(raw: str) -> dict:
    """
    Robustly extract a JSON object from K2's response.

    Attempts (in order):
      1. Strip think tags → direct json.loads
      2. Find the first { … } block in whatever remains
    Raises ValueError if neither attempt succeeds.
    """
    cleaned = strip_think_tags(raw)

    # Happy path
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fallback: find outermost braces
    start = cleaned.find("{")
    end   = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from K2 response:\n{raw[:500]}")

# ─── SAFE FALLBACK COMMAND ────────────────────────────────────────────────────
SAFE_COMMAND: dict = {
    "pwm":       [255, 255, 255, 255, 255,
                  200, 200, 200, 200, 200,
                  128, 128, 128, 128, 128, 128],
    "relay":     0,
    "lcd_line1": "K2 OFFLINE      ",
    "lcd_line2": "SAFE MODE       ",
    "reasoning": "K2 unreachable — safe fallback active.",
}

# ─── SYSTEM PROMPT ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are NEO — the Nodal Energy Oracle — the AI brain of a miniature smart city
power grid running on a physical Arduino breadboard. Your ONLY job is to output
a single JSON command object every control cycle. Do not explain yourself.
Do not add prose. Output ONLY valid JSON.

=== PHYSICAL SETUP ===
Two power sources:
  GREEN GRID : Solar (MB102). Cheap, clean, limited. Tracked by LDR.
  STATE GRID : Utility (5V 5A adapter). Expensive. Activated by Relay.
  RELAY CLICK costs relay_click reward points every time it switches ON.
  Two INA219 sensors: solar_ma (solar output) and load_ma (city draw).

24 LEDs across 4 tiers, controlled by a 16-channel PCA9685 PWM driver.
PWM values: 0 (off) to 255 (full brightness).

=== THE 4 TIERS ===
TIER 1 — CRITICAL  CH 0-1   (2 white LEDs)  HOSPITALS
  Always 255. Penalty tier1_dim per 1% reduction. Non-negotiable.

TIER 2 — ESSENTIAL CH 2-4   (3 red LEDs)    UTILITIES / INDUSTRY
  High priority. Use t2_demand_factor to scale target brightness.
  Penalty tier2_per10 per 10% dim below full.

TIER 3 — RESIDENTIAL CH 5-9 (5 green LEDs)  HOUSES
  Match potentiometer demand (pot1/pot2 avg, 0-1023 → PWM 0-255).
  Duck curve applies. Penalty tier3_outrage per 10% mismatch.

TIER 4 — COMMERCIAL CH 10-15 (6 yellow LEDs) MALLS
  Lowest priority — dim first when power is tight.
  Revenue tier4_revenue per second ON. Penalty tier4_per10 per 10% dim.

=== SENSOR INPUTS (you will receive all of these) ===
light              0-1023      LDR — higher = more solar available
temp_c             float       DHT11 temperature in Celsius
pressure_hpa       float       BMP180 pressure in hPa
solar_ma           float       INA219 solar output in mA
load_ma            float       INA219 city load in mA
pot1               0-1023      Residential demand knob A
pot2               0-1023      Residential demand knob B
tilt               0 or 1      Tilt switch: 1 = EARTHQUAKE lockdown
button             0-5         Mayor policy button last pressed (0=none)
battery_soc        0.0-1.0     Virtual battery state of charge
sim_hour           0.0-23.9    Simulated time of day
duck_demand        0.0-1.0     Expected residential demand this hour
relay_state        0 or 1      Current relay: 0=solar, 1=state grid
market_price       float       Live EIA-blended electricity price $/kWh

=== PRE-COMPUTED FORECAST SIGNALS (use these — do not rederive) ===
ttd_seconds            How many seconds until battery hits 0 at current drain
storm_probability      0.0-1.0 likelihood of incoming storm or cloud cover
solar_time_remaining   Seconds until LDR hits 0 at current declining slope
mins_to_demand_spike   Sim-minutes until next duck-curve spike (>= 70% demand)
t2_demand_factor       Temperature multiplier for T2 target (1.0 - 1.5)
dim_t4_recommended     bool: pre-computed optimizer says dim T4 now
recommended_t4_pwm     Suggested T4 PWM from break-even optimizer (0-255)
breakeven_ttd          TTD threshold below which dimming beats relay click
market_penalty_active  bool: market price alone warrants avoiding relay
sun_slope              Rate of change of light sensor (negative = clouds)
pressure_slope         Rate of change of pressure (negative = storm)

=== ACTIVE MAYOR POLICY FLAGS (injected when buttons are pressed) ===
policy_industrial_curfew   bool  T2 penalty weight halved — dim utilities freely
policy_solar_subsidy       bool  battery_soc already boosted +20% in this context
policy_brownout_protocol   bool  T3 penalty drastically reduced — allow 50% dim
policy_emergency_grid      bool  relay_click penalty zeroed — flip relay freely
policy_commercial_lockdown bool  T4 will be zeroed by Python regardless of your output

=== EARTHQUAKE LOCKDOWN (tilt = 1) ===
Immediately: T1=255, T2=255, T3=128, T4=0, relay=1, lcd="SEISMIC LOCKDOWN"

=== DECISION LOGIC (apply every cycle) ===
1. T1 always 255.
2. If tilt=1 → apply earthquake lockdown.
3. Use dim_t4_recommended and recommended_t4_pwm from the pre-computed optimizer.
   You may override these if other factors (market price, storm) justify it.
4. If storm_probability > 0.6 → aggressively pre-dim T4 regardless of battery.
5. If mins_to_demand_spike < 5 → start charging battery now (dim T4 early).
6. Battery rules:
   - soc > 0.8 and solar surplus → relay OFF, run solar.
   - soc < 0.2 → dim T4 aggressively.
   - soc < 0.05 → flip relay ON.
7. If market_penalty_active → avoid relay even at low soc. Dim everything except T1.
8. Scale T2 target by t2_demand_factor (extreme temps need more utilities power).

=== OUTPUT — ONLY THIS JSON, NOTHING ELSE ===
{
  "pwm": [255, 255, X, X, X, X, X, X, X, X, X, X, X, X, X, X],
  "relay": 0,
  "lcd_line1": "SOC:XX% $X.XX/kWh",
  "lcd_line2": "Score:XXXXX T4:XX%",
  "reasoning": "one sentence max"
}

pwm: exactly 16 integers (0-255). CH 0-1=T1, 2-4=T2, 5-9=T3, 10-15=T4.
relay: 0=solar only, 1=state grid ON.
lcd_line1 and lcd_line2: max 16 characters each (hard LCD constraint).
reasoning: one sentence explaining the main decision this cycle.
"""

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main() -> None:
    global battery_soc, reward_score

    # ── EIA cache warm-up ────────────────────────────────────────────────────
    if _EIA_AVAILABLE:
        try:
            warm_cache()
        except Exception as e:
            print(f"[WARN] EIA warm-up failed: {e}")

    # ── Dashboard thread ─────────────────────────────────────────────────────
    if _DASH_AVAILABLE:
        dash_thread = threading.Thread(target=run_dashboard, daemon=True)
        dash_thread.start()
        print("[NEO] Dashboard thread started.")

    # ── Policy engine ────────────────────────────────────────────────────────
    if _POLICY_AVAILABLE:
        policy = PolicyEngine(sim_start=SIM_START, sim_speed=SIM_SPEED)
        print("[NEO] Policy engine initialised.")
    else:
        policy = None

    # ── K2 client ────────────────────────────────────────────────────────────
    k2_client = OpenAI(api_key=K2_API_KEY, base_url=K2_BASE_URL)

    # ── Serial connection ────────────────────────────────────────────────────
    print(f"[NEO] Opening serial port {SERIAL_PORT} @ {BAUD_RATE} baud...")
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    except serial.SerialException as e:
        print(f"[FATAL] Cannot open serial port: {e}")
        print("        Set NEO_SERIAL_PORT env-var to the correct port.")
        sys.exit(1)
    time.sleep(2)   # wait for Arduino bootloader reset to finish
    print("[NEO] Serial connected. Starting control loop...\n")

    # ── Loop state ───────────────────────────────────────────────────────────
    prev_relay      = 0
    last_time       = time.time()
    last_k2_call    = 0.0
    current_command: dict | None = None
    k2_call_count   = 0

    # Debounce: only handle a button press once per physical press
    last_button_seen = 0

    # ── Control loop ─────────────────────────────────────────────────────────
    while True:
        loop_start = time.time()

        # ── 1. Read sensor CSV from Arduino ──────────────────────────────────
        try:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 9:
                continue
            sensor: dict = {
                "light":        int(parts[0]),
                "temp_c":       float(parts[1]),
                "pressure_hpa": float(parts[2]),
                "solar_ma":     float(parts[3]),
                "load_ma":      float(parts[4]),
                "pot1":         int(parts[5]),
                "pot2":         int(parts[6]),
                "tilt":         int(parts[7]),
                "button":       int(parts[8]),
            }
        except (ValueError, IndexError) as e:
            print(f"[SERIAL] Parse error ({e}): {line!r}")
            continue

        # ── 2. Update derived state ───────────────────────────────────────────
        now       = time.time()
        dt        = now - last_time
        last_time = now

        record_sensor(sensor)
        update_battery(sensor["solar_ma"], sensor["load_ma"], dt)

        sim_hour  = get_sim_hour()
        price     = get_price(sim_hour)

        # ── 3. Mayor policy button (edge-detect — one event per press) ────────
        btn = sensor["button"]
        if btn != 0 and btn != last_button_seen and policy is not None:
            name = policy.press(btn)
            if name:
                print(f"[MAYOR] Policy enacted: {name}")
        last_button_seen = btn

        # Get current effective weights and policy context tweaks
        weights        = policy.get_weights()       if policy else dict(BASE_PENALTY_WEIGHTS)
        policy_tweaks  = policy.get_context_tweaks() if policy else {}
        policy_status  = policy.status_dict()        if policy else {"active_policy": "None", "active_policies": [], "policy_expires_in": 0.0, "policy_real_expires": 0.0}

        # Solar Subsidy: boost the SoC seen by K2 and the forecaster
        effective_soc = battery_soc
        if policy_tweaks.get("policy_solar_subsidy"):
            effective_soc = min(1.0, battery_soc + policy_tweaks.get("soc_bonus", 0.20))

        # ── 4. Run forecaster ─────────────────────────────────────────────────
        if _FORECAST_AVAILABLE:
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
            # Minimal fallback slope computation if forecaster is missing
            def _slope(key: str, w: int = 5) -> float:
                if len(history) < 2: return 0.0
                v = [r[key] for r in history[-w:]]
                return (v[-1] - v[0]) / max(len(v) - 1, 1)
            forecast = {
                "sun_slope":             round(_slope("light"),         2),
                "pressure_slope":        round(_slope("pressure_hpa"),  4),
                "ttd_seconds":           99999.0,
                "storm_probability":     0.0,
                "solar_time_remaining":  99999.0,
                "mins_to_demand_spike":  9999.0,
                "t2_demand_factor":      1.0,
                "dim_t4_recommended":    False,
                "recommended_t4_pwm":    255,
                "breakeven_ttd":         0.0,
                "market_penalty_active": price > 2.0,
            }

        # ── 5. Build K2 context object ────────────────────────────────────────
        context: dict = {
            # Raw sensor data
            **sensor,
            # Derived grid state
            "battery_soc":    round(effective_soc, 3),
            "sim_hour":       round(sim_hour, 2),
            "duck_demand":    round(get_duck_demand(), 2),
            "relay_state":    prev_relay,
            "market_price":   price,
            "reward_score":   round(reward_score, 1),
            # Pre-computed forecast signals (from forecaster.py)
            **forecast,
            # Active policy flags (from policy_engine.py)
            **{k: v for k, v in policy_tweaks.items() if k != "soc_bonus"},
        }

        # ── 6. Call K2 Think V2 every K2_CALL_INTERVAL seconds ───────────────
        if now - last_k2_call >= K2_CALL_INTERVAL:
            last_k2_call  = now
            k2_call_count += 1
            try:
                response = k2_client.chat.completions.create(
                    model       = K2_MODEL,
                    max_tokens  = 512,    # enough for think block + JSON
                    temperature = 0.1,    # near-deterministic grid decisions
                    messages    = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": json.dumps(context)},
                    ],
                )
                raw             = response.choices[0].message.content or ""
                current_command = extract_json(raw)

                # Validate PWM array
                if len(current_command.get("pwm", [])) != 16:
                    raise ValueError("pwm array must have exactly 16 values")

                # Hard safety override — never let K2 dim hospitals
                current_command["pwm"][0] = 255
                current_command["pwm"][1] = 255

                print(f"[K2 #{k2_call_count}] {current_command.get('reasoning', '')}")

            except Exception as e:
                print(f"[K2 ERROR #{k2_call_count}] {e}")
                current_command = dict(SAFE_COMMAND)

        if current_command is None:
            time.sleep(0.05)
            continue

        # ── 7. Apply hard policy overrides AFTER K2 decision ─────────────────
        # These happen in Python, not in the prompt — they are guaranteed.

        # Commercial Lockdown (Button 5): zero all T4 channels, no exceptions
        if policy is not None and policy.commercial_lockdown_active():
            for ch in range(10, 16):
                current_command["pwm"][ch] = 0

        # Earthquake Lockdown (tilt sensor): override everything
        if sensor["tilt"] == 1:
            current_command["pwm"][0]  = 255   # T1 hospitals
            current_command["pwm"][1]  = 255
            current_command["pwm"][2]  = 255   # T2 utilities
            current_command["pwm"][3]  = 255
            current_command["pwm"][4]  = 255
            current_command["pwm"][5]  = 128   # T3 residential half-power
            current_command["pwm"][6]  = 128
            current_command["pwm"][7]  = 128
            current_command["pwm"][8]  = 128
            current_command["pwm"][9]  = 128
            for ch in range(10, 16):           # T4 commercial off
                current_command["pwm"][ch] = 0
            current_command["relay"]     = 1
            current_command["lcd_line1"] = "SEISMIC LOCKDOWN"
            current_command["lcd_line2"] = "ALL CLEAR NEEDED"
            current_command["reasoning"] = "Earthquake lockdown — tilt sensor fired."

        # ── 8. Compute reward ─────────────────────────────────────────────────
        reward_score = compute_reward(
            pwm        = current_command["pwm"],
            relay      = current_command["relay"],
            pot1       = sensor["pot1"],
            pot2       = sensor["pot2"],
            prev_relay = prev_relay,
            weights    = weights,
        )
        prev_relay = current_command["relay"]

        # ── 9. Grid fault detection (audit loop) ─────────────────────────────
        # If the AI commanded a significant T4 dim but INA219 load didn't drop,
        # flag a hardware fault — could be a wiring fault or "energy theft."
        fault_msg = ""
        if len(history) >= 4:
            prev_load    = history[-4]["load_ma"]
            this_load    = sensor["load_ma"]
            t4_avg       = sum(current_command["pwm"][10:16]) / 6.0
            load_change  = abs(this_load - prev_load)
            if t4_avg < 30 and load_change < 5.0 and prev_load > 50:
                fault_msg = f"Grid Fault: T4 dim but load unchanged ({this_load:.0f} mA)"
                print(f"[FAULT] {fault_msg}")

        # ── 10. Send command string to Arduino ───────────────────────────────
        pwm_str = ",".join(str(v) for v in current_command["pwm"])
        lcd1    = current_command.get("lcd_line1", "NEO RUNNING     ")[:16].ljust(16)
        lcd2    = current_command.get("lcd_line2", "                ")[:16].ljust(16)
        cmd_str = (
            f"PWM:{pwm_str},"
            f"RELAY:{current_command['relay']},"
            f"LCD1:{lcd1},"
            f"LCD2:{lcd2}\n"
        )
        try:
            ser.write(cmd_str.encode("utf-8"))
        except serial.SerialException as e:
            print(f"[SERIAL] Write error: {e}")

        # ── 11. Push state to dashboard ───────────────────────────────────────
        eia_status: dict = {}
        if _EIA_AVAILABLE:
            try:
                eia_status = get_cache_status()
            except Exception:
                pass

        loop_ms = (time.time() - loop_start) * 1000.0

        dash_update({
            # Grid
            "battery_soc":    battery_soc,      # real SoC (not subsidy-boosted)
            "sim_hour":       sim_hour,
            "market_price":   price,
            "relay":          current_command["relay"],
            "reward_score":   reward_score,
            # Sensors
            "light":          sensor["light"],
            "temp_c":         sensor["temp_c"],
            "pressure_hpa":   sensor["pressure_hpa"],
            "solar_ma":       sensor["solar_ma"],
            "load_ma":        sensor["load_ma"],
            "pot1":           sensor["pot1"],
            "pot2":           sensor["pot2"],
            "tilt":           sensor["tilt"],
            "button":         sensor["button"],
            # Forecast (from forecaster.py)
            "sun_slope":              forecast.get("sun_slope", 0.0),
            "pressure_slope":         forecast.get("pressure_slope", 0.0),
            "duck_demand":            get_duck_demand(),
            "storm_probability":      forecast.get("storm_probability", 0.0),
            "ttd_seconds":            forecast.get("ttd_seconds", 99999.0),
            "dim_t4_recommended":     forecast.get("dim_t4_recommended", False),
            "recommended_t4_pwm":     forecast.get("recommended_t4_pwm", 255),
            "mins_to_demand_spike":   forecast.get("mins_to_demand_spike", 9999.0),
            # AI
            "pwm":            current_command["pwm"],
            "reasoning":      current_command.get("reasoning", ""),
            # EIA
            "eia_retail":     eia_status.get("retail_usd_per_kwh", 0.17),
            "eia_demand_mw":  eia_status.get("demand_mw",          400_000.0),
            "eia_live":       eia_status.get("live",                False),
            "eia_age_s":      eia_status.get("age_seconds",         0.0),
            # Policy
            **policy_status,
            # Meta
            "fault":          fault_msg,
            "loop_ms":        loop_ms,
            "k2_calls":       k2_call_count,
        })

        # ── 12. Pace the loop to ~100 ms ─────────────────────────────────────
        elapsed = time.time() - loop_start
        sleep_s = max(0.0, (LOOP_INTERVAL_MS / 1000.0) - elapsed)
        time.sleep(sleep_s)


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  NEO — Nodal Energy Oracle")
    print("  YHack 2025")
    print("=" * 60)
    print(f"  Serial port  : {SERIAL_PORT}")
    print(f"  K2 model     : {K2_MODEL}")
    print(f"  EIA client   : {'enabled' if _EIA_AVAILABLE else 'SIMULATED'}")
    print(f"  Forecaster   : {'enabled' if _FORECAST_AVAILABLE else 'DISABLED'}")
    print(f"  Policy engine: {'enabled' if _POLICY_AVAILABLE else 'DISABLED'}")
    print(f"  Dashboard    : {'enabled' if _DASH_AVAILABLE else 'headless'}")
    print("=" * 60 + "\n")
    main()
