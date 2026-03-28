# ============================================================
#  NEO — Nodal Energy Oracle
#  backend/main.py  —  AI Control Loop
#  YHack 2025
#
#  ROLE: AI / Backend Engineer owns this file.
#
#  Responsibilities:
#    - 100 ms serial loop: read Arduino CSV → send command string
#    - Call K2 Think V2 every 2 s for grid decisions
#    - Strip <think>…</think> reasoning blocks from K2 response
#    - Integrate EIA live market price (eia_client.py)
#    - Push state to terminal dashboard (../frontend/dashboard.py)
#    - Maintain virtual battery, duck curve, reward score
#
#  Serial protocol (must match neo_arduino.ino exactly)
#    RX from Arduino (100 ms):
#      "light,temp_c,pressure_hpa,solar_ma,load_ma,pot1,pot2,tilt,button\n"
#    TX to Arduino (after each K2 decision):
#      "PWM:v0,...,v15,RELAY:r,LCD1:line1,LCD2:line2\n"
#
#  Environment variables (set before running):
#    NEO_SERIAL_PORT   default COM3  (Mac/Linux: /dev/tty.usbmodemXXX)
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

# ── Path setup so we can import sibling packages ──────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
SERIAL_PORT  = os.environ.get("NEO_SERIAL_PORT", "COM3")
BAUD_RATE    = 9600

K2_API_KEY   = os.environ.get("K2_API_KEY",  "YOUR_K2_KEY_HERE")
K2_BASE_URL  = "https://api.k2think.ai/v1"
K2_MODEL     = "MBZUAI-IFM/K2-Think-v2"   # ← exact model ID from the API docs

K2_CALL_INTERVAL  = 2.0    # seconds between K2 API calls (budget management)
LOOP_INTERVAL_MS  = 100    # target control loop period in ms

# ─── PENALTY / REWARD WEIGHTS ─────────────────────────────────────────────────
# The Mayor can alter these at runtime via button presses.
PENALTY_WEIGHTS = {
    "tier1_dim":     -1000,   # per 1 % reduction — catastrophic
    "tier2_per10":   -50,     # per 10 % dim below full
    "tier3_outrage": -20,     # per 10 % mismatch vs potentiometer demand
    "tier4_per10":   -5,      # per 10 % dim (minor — T4 is the buffer)
    "relay_click":   -500,    # every time relay switches ON
    "tier4_revenue": +10,     # per second commercial LEDs are lit
}

# ─── MAYOR POLICY REGISTRY ────────────────────────────────────────────────────
POLICY_LABELS = {
    0: "None",
    1: "Industrial Curfew",
    2: "Solar Subsidy",
    3: "Brownout Protocol",
    4: "Emergency Grid",
    5: "Commercial Lockdown",
}

# ─── SIMULATED CLOCK ──────────────────────────────────────────────────────────
SIM_START = time.time()
SIM_SPEED = 60   # 1 real second = 60 simulated seconds  →  1 real minute = 1 sim hour

def get_sim_hour() -> float:
    elapsed = time.time() - SIM_START
    return (elapsed * SIM_SPEED / 3600.0) % 24.0

# ─── DUCK CURVE ───────────────────────────────────────────────────────────────
DUCK_CURVE = {
    0:  0.20, 1:  0.15, 2:  0.10, 3:  0.10, 4:  0.10, 5:  0.20,
    6:  0.50, 7:  0.80, 8:  0.70, 9:  0.50, 10: 0.40, 11: 0.30,
    12: 0.25, 13: 0.25, 14: 0.30, 15: 0.35, 16: 0.50,
    17: 0.70, 18: 0.90, 19: 1.00, 20: 0.95, 21: 0.80,
    22: 0.60, 23: 0.40,
}

def get_duck_demand() -> float:
    return DUCK_CURVE[int(get_sim_hour()) % 24]

# ─── FALLBACK MARKET PRICE (used only if eia_client unavailable) ──────────────
def _simulated_market_price(sim_hour: float) -> float:
    if   7  <= sim_hour < 9:    base = 2.5
    elif 18 <= sim_hour < 21:   base = 3.0
    elif 0  <= sim_hour < 5:    base = 0.5
    else:                        base = 1.0
    noise = math.sin(time.time() * 0.1) * 0.2
    return round(max(0.5, min(3.0, base + noise)), 2)

def get_price(sim_hour: float) -> float:
    if _EIA_AVAILABLE:
        return get_market_price(sim_hour)
    return _simulated_market_price(sim_hour)

# ─── VIRTUAL BATTERY ──────────────────────────────────────────────────────────
battery_soc          = 0.50   # 0.0 – 1.0
BATTERY_CAPACITY_MAH = 2000.0

def update_battery(solar_ma: float, load_ma: float, dt: float) -> None:
    global battery_soc
    net_ma = solar_ma - load_ma
    # Δ SoC = (net current × time) / capacity
    delta = (net_ma * dt) / (BATTERY_CAPACITY_MAH * 3600.0)
    battery_soc = max(0.0, min(1.0, battery_soc + delta))

# ─── SENSOR HISTORY & SLOPE ───────────────────────────────────────────────────
history: list[dict] = []

def record_sensor(sensor: dict) -> None:
    history.append(sensor)
    if len(history) > 20:
        history.pop(0)

def compute_slope(key: str, window: int = 5) -> float:
    if len(history) < 2:
        return 0.0
    recent = history[-window:]
    vals   = [r[key] for r in recent]
    return (vals[-1] - vals[0]) / max(len(vals) - 1, 1)

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

    # Tier 1 — hospitals must always be at 255
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

    # Relay click penalty (only on transition OFF → ON)
    if relay == 1 and prev_relay == 0:
        r += weights["relay_click"]

    reward_score += r
    return reward_score

# ─── THINK-TAG STRIPPER ───────────────────────────────────────────────────────
# K2 Think V2 prefixes its JSON with a <think>…</think> reasoning block.
# We must remove it before calling json.loads().

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

def strip_think_tags(raw: str) -> str:
    """Remove K2's <think>…</think> block and return only the JSON payload."""
    cleaned = _THINK_RE.sub("", raw).strip()
    # Also handle cases where the model forgets the closing tag
    if "<think>" in cleaned:
        cleaned = cleaned[cleaned.rfind("</think>") + 8:].strip() if "</think>" in cleaned \
                  else cleaned.split("<think>")[0].strip()
    return cleaned

def extract_json(raw: str) -> dict:
    """
    Robustly extract a JSON object from K2's response.
    Tries (in order):
      1. Strip think tags → direct parse
      2. Find the first { … } block in whatever remains
    """
    cleaned = strip_think_tags(raw)

    # Direct parse (happy path)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fallback: find outermost { } block
    start = cleaned.find("{")
    end   = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from K2 response:\n{raw[:400]}")

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
The city has two power sources:
  - GREEN GRID: Solar (MB102 module). Cheap, clean, but limited. Tracked by LDR sensor.
  - STATE GRID: Utility (5V 5A adapter). Expensive. Activated by a mechanical Relay.
  - RELAY CLICK costs -500 reward points every time it switches ON.
  - Two INA219 current sensors measure real milliamps: one on solar, one on the city load.

The city has 24 LEDs organized into 4 tiers, controlled by a 16-channel PCA9685 PWM driver.
Each LED brightness is a PWM value 0 (off) to 255 (full).

=== THE 4 TIERS ===
TIER 1 — CRITICAL (2 white LEDs: channels 0,1) — HOSPITALS
  Must ALWAYS be at PWM 255. Penalty: -1000 per 1% reduction.

TIER 2 — ESSENTIAL (3 red LEDs: channels 2,3,4) — UTILITIES / INDUSTRY
  High priority. Demand scales with temperature: if temp > 25°C, demand increases 20%.
  Penalty: -50 per 10% dim below full.

TIER 3 — RESIDENTIAL (5 green LEDs: channels 5,6,7,8,9) — HOUSES
  Must match potentiometer demand (pot1/pot2 average, 0–1023 → PWM 0–255).
  Duck Curve applies: demand spikes at 7AM and 7PM.
  Penalty: -20 per 10% mismatch between LED brightness and pot demand.

TIER 4 — COMMERCIAL (6 yellow LEDs: channels 10,11,12,13,14,15) — MALLS
  Lowest priority. Dim these first when power is tight.
  Revenue: +10 reward points per second they are ON.
  Penalty: -5 per 10% dim (minor).

=== SENSOR INPUTS ===
{
  "light": 0-1023,          // LDR: higher = more solar available
  "temp_c": float,          // DHT11 temperature in Celsius
  "pressure_hpa": float,    // BMP180 pressure in hPa
  "solar_ma": float,        // INA219 #1: milliamps from solar side
  "load_ma": float,         // INA219 #2: milliamps city is drawing
  "pot1": 0-1023,           // Residential zone A demand knob
  "pot2": 0-1023,           // Residential zone B demand knob
  "tilt": 0 or 1,           // Tilt switch: 1 = EARTHQUAKE lockdown
  "button": 0-5,            // Mayor policy button (0 = none)
  "battery_soc": 0.0-1.0,   // Virtual battery state of charge
  "sim_hour": 0.0-23.9,     // Simulated time of day
  "duck_demand": 0.0-1.0,   // Expected residential demand this hour
  "sun_slope": float,       // Rate of change of light sensor (neg = clouds)
  "pressure_slope": float,  // Rate of change of pressure (neg = storm)
  "reward_score": float,    // Running total reward score
  "relay_state": 0 or 1,    // Current relay state
  "market_price": float     // Live EIA-blended electricity price ($/kWh)
}

=== MAYOR POLICY BUTTONS ===
Button 1 — Industrial Curfew:   T2 penalty weight × 0.5 for 60 sim-seconds.
Button 2 — Solar Subsidy:       Treat battery_soc as 20% higher this cycle.
Button 3 — Brownout Protocol:   T3 can drop to 50% with no outrage penalty.
Button 4 — Emergency Grid:      Ignore relay penalty this cycle.
Button 5 — Commercial Lockdown: Force T4 to 0, no revenue, no penalty.

=== EARTHQUAKE LOCKDOWN (tilt = 1) ===
Set T1=255, T2=255, T3=128, T4=0. relay=1. lcd_message="SEISMIC LOCKDOWN".

=== DECISION LOGIC ===
1. SAFETY: T1 always 255.
2. EARTHQUAKE: If tilt=1 apply lockdown.
3. STORM PREDICTION: If pressure_slope < -0.5 or sun_slope < -20, pre-dim T4.
4. DUCK CURVE: At sim_hour 16-17 start charging battery by dimming T4.
5. BATTERY:
   - soc > 0.8 and solar surplus → relay OFF, run solar.
   - soc < 0.2 → dim T4 aggressively.
   - soc < 0.05 → flip relay ON.
6. MARKET PRICE: If market_price > 2.0, avoid relay even at low soc.
7. REWARD MATH: Is dimming T4 now worth avoiding -500 relay click later?

=== OUTPUT FORMAT — ONLY THIS JSON, NOTHING ELSE ===
{
  "pwm": [255, 255, X, X, X, X, X, X, X, X, X, X, X, X, X, X],
  "relay": 0,
  "lcd_line1": "SOC:XX% $X.XX/kWh",
  "lcd_line2": "Score:XXXXX T4:XX%",
  "reasoning": "one sentence max"
}

pwm: exactly 16 integers (0-255). CH 0-1=T1, 2-4=T2, 5-9=T3, 10-15=T4.
relay: 0=solar, 1=state grid.
lcd_line1 and lcd_line2: max 16 characters each.
reasoning: one sentence only.
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
    time.sleep(2)   # wait for Arduino bootloader to finish
    print("[NEO] Serial connected. Starting control loop...\n")

    # ── Loop state ───────────────────────────────────────────────────────────
    prev_relay      = 0
    last_time       = time.time()
    last_k2_call    = 0.0
    current_command = None
    active_policy   = "None"
    k2_call_count   = 0
    weights         = dict(PENALTY_WEIGHTS)   # mutable copy for policy tweaks

    # ── Control loop ─────────────────────────────────────────────────────────
    while True:
        loop_start = time.time()

        # ── 1. Read sensor CSV from Arduino ─────────────────────────────────
        try:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 9:
                continue
            sensor = {
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

        # ── 2. Update derived state ──────────────────────────────────────────
        now  = time.time()
        dt   = now - last_time
        last_time = now

        record_sensor(sensor)
        update_battery(sensor["solar_ma"], sensor["load_ma"], dt)

        sim_hour  = get_sim_hour()
        price     = get_price(sim_hour)

        # ── 3. Apply mayor policy button (edge — one shot per press) ─────────
        btn = sensor["button"]
        if btn in (1, 2, 3, 4, 5):
            active_policy = POLICY_LABELS[btn]
            print(f"[MAYOR] Policy enacted: {active_policy}")

            if btn == 1:   # Industrial Curfew — ease T2 penalty
                weights["tier2_per10"] = PENALTY_WEIGHTS["tier2_per10"] * 0.5
            elif btn == 5: # Commercial Lockdown — forced in K2 prompt
                pass       # K2 sees the button value and acts accordingly
            # Buttons 2, 3, 4 are context hints sent to K2 via the sensor dict

        # ── 4. Build K2 context object ───────────────────────────────────────
        context = {
            **sensor,
            "battery_soc":    round(battery_soc, 3),
            "sim_hour":       round(sim_hour, 2),
            "duck_demand":    round(get_duck_demand(), 2),
            "sun_slope":      round(compute_slope("light"), 2),
            "pressure_slope": round(compute_slope("pressure_hpa"), 4),
            "reward_score":   round(reward_score, 1),
            "relay_state":    prev_relay,
            "market_price":   price,
        }

        # ── 5. Call K2 Think V2 every K2_CALL_INTERVAL seconds ───────────────
        if now - last_k2_call >= K2_CALL_INTERVAL:
            last_k2_call = now
            k2_call_count += 1
            try:
                response = k2_client.chat.completions.create(
                    model=K2_MODEL,
                    max_tokens=512,       # enough for JSON + think block
                    temperature=0.1,      # near-deterministic grid decisions
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": json.dumps(context)},
                    ],
                )
                raw           = response.choices[0].message.content or ""
                current_command = extract_json(raw)
                # Validate PWM array length
                if len(current_command.get("pwm", [])) != 16:
                    raise ValueError("pwm array must have exactly 16 values")
                # Enforce T1 safety — never let K2 dim hospitals
                current_command["pwm"][0] = 255
                current_command["pwm"][1] = 255
                print(f"[K2 #{k2_call_count}] {current_command['reasoning']}")

            except Exception as e:
                print(f"[K2 ERROR] {e}")
                current_command = dict(SAFE_COMMAND)

        if current_command is None:
            time.sleep(0.05)
            continue

        # ── 6. Compute reward ─────────────────────────────────────────────────
        reward_score = compute_reward(
            pwm        = current_command["pwm"],
            relay      = current_command["relay"],
            pot1       = sensor["pot1"],
            pot2       = sensor["pot2"],
            prev_relay = prev_relay,
            weights    = weights,
        )
        prev_relay = current_command["relay"]

        # ── 7. Grid fault detection (audit) ──────────────────────────────────
        # If AI commanded a significant load drop but INA219 shows no change,
        # flag a hardware fault on the dashboard.
        fault_msg = ""
        if len(history) >= 3:
            prev_load  = history[-3]["load_ma"]
            this_load  = sensor["load_ma"]
            t4_avg_new = sum(current_command["pwm"][10:16]) / 6.0
            if t4_avg_new < 50 and abs(this_load - prev_load) < 5:
                fault_msg = "Grid Fault: load unchanged after dim"

        # ── 8. Send command string to Arduino ────────────────────────────────
        pwm_str = ",".join(str(v) for v in current_command["pwm"])
        lcd1    = current_command.get("lcd_line1", "NEO RUNNING     ")[:16].ljust(16)
        lcd2    = current_command.get("lcd_line2", "                ")[:16].ljust(16)
        cmd     = (
            f"PWM:{pwm_str},"
            f"RELAY:{current_command['relay']},"
            f"LCD1:{lcd1},"
            f"LCD2:{lcd2}\n"
        )
        try:
            ser.write(cmd.encode("utf-8"))
        except serial.SerialException as e:
            print(f"[SERIAL] Write error: {e}")

        # ── 9. Push state to dashboard ────────────────────────────────────────
        eia_status = {}
        if _EIA_AVAILABLE:
            try:
                eia_status = get_cache_status()
            except Exception:
                pass

        loop_ms = (time.time() - loop_start) * 1000.0

        dash_update({
            # Grid
            "battery_soc":    battery_soc,
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
            # Forecast
            "sun_slope":      context["sun_slope"],
            "pressure_slope": context["pressure_slope"],
            "duck_demand":    context["duck_demand"],
            # AI
            "pwm":            current_command["pwm"],
            "reasoning":      current_command.get("reasoning", ""),
            # EIA
            "eia_retail":     eia_status.get("retail_usd_per_kwh", 0.17),
            "eia_demand_mw":  eia_status.get("demand_mw",          400_000.0),
            "eia_live":       eia_status.get("live",                False),
            "eia_age_s":      eia_status.get("age_seconds",         0.0),
            # Meta
            "active_policy":  active_policy,
            "fault":          fault_msg,
            "loop_ms":        loop_ms,
            "k2_calls":       k2_call_count,
        })

        # ── 10. Pace the loop to ~100 ms ─────────────────────────────────────
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
    print(f"  Dashboard    : {'enabled' if _DASH_AVAILABLE else 'headless'}")
    print("=" * 60 + "\n")
    main()
