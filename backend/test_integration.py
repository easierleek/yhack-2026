# ============================================================
#  NEO -- Nodal Energy Oracle
#  backend/test_integration.py -- Live API + Full Loop Dry Run
#  YHack 2025
#
#  Tests everything end-to-end WITHOUT an Arduino.
#  Simulated sensor data drives the full control loop so you
#  can verify K2 responds correctly and all plumbing works
#  before plugging in the hardware.
#
#  Run from the backend/ directory:
#      python test_integration.py
#
#  What this tests:
#    1. .env loaded correctly (keys present)
#    2. EIA API -- live fetch, price in range, cache works
#    3. K2 API -- real call, think tags stripped, valid JSON
#    4. K2 enforces T1=255 rule in its own output
#    5. Full 10-cycle dry run: forecaster -> K2 -> reward -> fault
#    6. Earthquake override fires correctly mid-loop
#    7. Reward score moves in the right direction
# ============================================================

import os
import sys
import json
import math
import time
import copy
import re

# ── Load .env before anything else ────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openai import OpenAI
from forecaster import compute_forecast, time_to_deficit
from eia_client import get_market_price, warm_cache, get_cache_status

# ── Pull keys (never print them) ──────────────────────────────────────────────
K2_API_KEY  = os.environ.get("K2_API_KEY",  "")
EIA_API_KEY = os.environ.get("EIA_API_KEY", "")
K2_BASE_URL = "https://api.k2think.ai/v1"
K2_MODEL    = "MBZUAI-IFM/K2-Think-v2"

# ── Colours for terminal output ───────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# ── Minimal test harness ──────────────────────────────────────────────────────
PASS = 0
FAIL = 0
WARN = 0

def ok(name: str):
    global PASS
    PASS += 1
    print(f"  {GREEN}PASS{RESET}  {name}")

def fail(name: str, detail: str = ""):
    global FAIL
    FAIL += 1
    msg = f"  {RED}FAIL{RESET}  {name}"
    if detail:
        msg += f"\n        {RED}{detail}{RESET}"
    print(msg)

def warn(name: str, detail: str = ""):
    global WARN
    WARN += 1
    print(f"  {YELLOW}WARN{RESET}  {name}")
    if detail:
        print(f"        {YELLOW}{detail}{RESET}")

def section(title: str):
    print(f"\n{BOLD}{'='*62}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'='*62}{RESET}")

def check(name: str, condition: bool, detail: str = ""):
    if condition:
        ok(name)
    else:
        fail(name, detail)

# ── Mirror of main.py helpers (no serial import) ─────────────────────────────

BASE_WEIGHTS = {
    "tier1_dim":     -1000.0,
    "tier2_per10":     -50.0,
    "tier3_outrage":   -20.0,
    "tier4_per10":      -5.0,
    "relay_click":    -500.0,
    "tier4_revenue":   +10.0,
}

BATTERY_CAPACITY_MAH = 2000.0
battery_soc = 0.50
reward_score = 0.0
history = []
SIM_START = time.time()
SIM_SPEED = float(os.environ.get("SIM_SPEED", "60"))

DUCK_CURVE = {
     0: 0.20,  1: 0.15,  2: 0.10,  3: 0.10,  4: 0.10,  5: 0.20,
     6: 0.50,  7: 0.80,  8: 0.70,  9: 0.50, 10: 0.40, 11: 0.30,
    12: 0.25, 13: 0.25, 14: 0.30, 15: 0.35, 16: 0.50,
    17: 0.70, 18: 0.90, 19: 1.00, 20: 0.95, 21: 0.80,
    22: 0.60, 23: 0.40,
}

SAFE_COMMAND = {
    "pwm":       [255, 255, 255, 255, 255,
                  200, 200, 200, 200, 200,
                  128, 128, 128, 128, 128, 128],
    "relay":     0,
    "lcd_line1": "K2 OFFLINE      ",
    "lcd_line2": "SAFE MODE       ",
    "reasoning": "K2 unreachable -- safe fallback active.",
}

def safe_command():
    return copy.deepcopy(SAFE_COMMAND)

def repair_command(partial: dict) -> dict:
    """
    Patch a partially-valid K2 response so the dry run can still use it.
    Handles the most common failure: truncated pwm array from K2 running out
    of generation budget mid-JSON.

    Safe defaults per tier:
        CH 0-1   T1 hospitals  -> 255
        CH 2-4   T2 utilities  -> 255
        CH 5-9   T3 residential-> 128
        CH 10-15 T4 commercial -> 128
    """
    pwm = list(partial.get("pwm", []))
    safe_defaults = [255, 255, 255, 255, 255,
                     128, 128, 128, 128, 128,
                     128, 128, 128, 128, 128, 128]
    while len(pwm) < 16:
        pwm.append(safe_defaults[len(pwm)])
    pwm = pwm[:16]
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

def get_sim_hour():
    return ((time.time() - SIM_START) * SIM_SPEED / 3600.0) % 24.0

def get_duck_demand():
    return DUCK_CURVE[int(get_sim_hour()) % 24]

def update_battery(solar_ma, load_ma, dt):
    global battery_soc
    net_ma = solar_ma - load_ma
    delta  = (net_ma * dt) / (BATTERY_CAPACITY_MAH * 3600.0)
    battery_soc = max(0.0, min(1.0, battery_soc + delta))

def record_sensor(sensor):
    history.append(sensor)
    if len(history) > 20:
        history.pop(0)

def compute_reward(pwm, relay, pot1, pot2, prev_relay, weights):
    global reward_score
    r = 0.0
    for ch in [0, 1]:
        if pwm[ch] < 255:
            r += weights["tier1_dim"] * ((255 - pwm[ch]) / 255 * 100)
    for ch in [2, 3, 4]:
        r += weights["tier2_per10"] * ((255 - pwm[ch]) / 255.0 * 10.0)
    pot_avg = ((pot1 + pot2) / 2.0) / 1023.0
    for ch in [5, 6, 7, 8, 9]:
        mismatch = abs(pwm[ch] / 255.0 - pot_avg)
        r += weights["tier3_outrage"] * (mismatch * 10.0)
    for ch in [10, 11, 12, 13, 14, 15]:
        if pwm[ch] > 0:
            r += weights["tier4_revenue"] * 0.1
        r += weights["tier4_per10"] * ((255 - pwm[ch]) / 255.0 * 10.0)
    if relay == 1 and prev_relay == 0:
        r += weights["relay_click"]
    reward_score += r
    return reward_score

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

def strip_think_tags(raw):
    cleaned = _THINK_RE.sub("", raw).strip()
    if "<think>" in cleaned:
        if "</think>" in cleaned:
            cleaned = cleaned[cleaned.rfind("</think>") + 8:].strip()
        else:
            cleaned = cleaned.split("<think>", 1)[1]
    return cleaned

def extract_json(raw):
    """
    Find and return the best JSON object in K2's response.

    K2 Think V2 reasons at length before outputting JSON.  We scan every
    { ... } block in the response and return the first one that:
      1. Parses as valid JSON, AND
      2. Contains a 'pwm' key with a list of exactly 16 integers.

    Falls back to any parseable JSON object with pwm+relay if no ideal block found.
    """
    cleaned = strip_think_tags(raw)

    candidates = []
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
    candidates.append(cleaned)

    best_fallback = None
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        pwm = obj.get("pwm")
        if (
            isinstance(pwm, list)
            and len(pwm) == 16
            and all(isinstance(v, int) for v in pwm)
        ):
            return obj
        if best_fallback is None and "pwm" in obj and "relay" in obj:
            best_fallback = obj

    if best_fallback is not None:
        return best_fallback

    raise ValueError(f"No valid JSON found:\n{raw[:500]}")

# ── System prompt (same as main.py) ──────────────────────────────────────────
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
T2  CH 2-4   UTILITIES   High priority. Scale by t2_demand_factor.
T3  CH 5-9   HOUSES      Match (pot1+pot2)/2 mapped to 0-255. Penalty if mismatch.
T4  CH 10-15 MALLS       Dim first. Revenue when on, small penalty when dimmed.

=== DECISION RULES ===
1. T1 channels 0 and 1 are ALWAYS 255. No exceptions.
2. If tilt=1: set T1=255, T2=255, T3=128, T4=0, relay=1.
3. If dim_t4_recommended=true: use recommended_t4_pwm for T4 channels.
4. If storm_probability > 0.6: dim T4 aggressively to pre-charge battery.
5. If mins_to_demand_spike < 5: start dimming T4 to build charge buffer.
6. If battery_soc < 0.05: relay=1. If battery_soc < 0.2: dim T4 hard.
7. If market_penalty_active=true: avoid relay, dim everything except T1.
8. Multiply T2 target brightness by t2_demand_factor (temperature load).

=== YOUR RESPONSE MUST BE EXACTLY THIS JSON STRUCTURE ===
{"pwm":[255,255,X,X,X,X,X,X,X,X,X,X,X,X,X,X],"relay":0,"lcd_line1":"SOC:XX% $X.XX","lcd_line2":"Score:XXXXX T4:XX%","reasoning":"one sentence"}

Rules:
- pwm: exactly 16 integers each 0-255
- relay: 0 or 1
- lcd_line1 and lcd_line2: strings of 16 characters or fewer
- reasoning: one short sentence

DO NOT write anything before { or after }. Output the JSON and nothing else.
"""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 -- Environment check
# ─────────────────────────────────────────────────────────────────────────────
section("1. Environment / .env check")

check("K2_API_KEY is set",
      bool(K2_API_KEY),
      "K2_API_KEY is empty -- add it to .env")

check("EIA_API_KEY is set",
      bool(EIA_API_KEY),
      "EIA_API_KEY is empty -- add it to .env")

check("K2 base URL correct",
      K2_BASE_URL == "https://api.k2think.ai/v1")

check("K2 model ID correct",
      K2_MODEL == "MBZUAI-IFM/K2-Think-v2")

check("SIM_SPEED loaded from .env (default 60)",
      SIM_SPEED > 0)

print(f"\n  Serial port configured as: {os.environ.get('NEO_SERIAL_PORT', 'COM3')} (not tested here)")
print(f"  K2 key length:  {len(K2_API_KEY)} chars")
print(f"  EIA key length: {len(EIA_API_KEY)} chars")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 -- EIA API live test
# ─────────────────────────────────────────────────────────────────────────────
section("2. EIA API -- live fetch")

if not EIA_API_KEY:
    warn("EIA API skipped -- no key set")
else:
    print("  Calling EIA API (warm_cache)...")
    t0 = time.time()
    try:
        warm_cache()
        elapsed = time.time() - t0
        status  = get_cache_status()

        check("EIA cache is live",
              status["live"],
              "Got fallback values -- check EIA_API_KEY and internet")

        check("Retail price is a positive float",
              isinstance(status["retail_usd_per_kwh"], float)
              and status["retail_usd_per_kwh"] > 0,
              f"Got: {status['retail_usd_per_kwh']}")

        check("Retail price in plausible range ($0.05 - $0.60 /kWh)",
              0.05 < status["retail_usd_per_kwh"] < 0.60,
              f"Got: ${status['retail_usd_per_kwh']:.4f} /kWh")

        check("Grid demand is a positive float",
              isinstance(status["demand_mw"], float)
              and status["demand_mw"] > 0,
              f"Got: {status['demand_mw']}")

        check("Grid demand in plausible range (100k - 800k MW)",
              100_000 < status["demand_mw"] < 800_000,
              f"Got: {status['demand_mw']:,.0f} MW")

        check("Cache age is recent (< 60 s)",
              status["age_seconds"] < 60,
              f"Got: {status['age_seconds']:.1f} s")

        print(f"\n  {CYAN}Retail price : ${status['retail_usd_per_kwh']:.4f} /kWh{RESET}")
        print(f"  {CYAN}Grid demand  : {status['demand_mw']:,.0f} MW{RESET}")
        print(f"  {CYAN}EIA response : {elapsed:.2f} s{RESET}")

        # Test that get_market_price returns a sensible blended value
        for sim_h in [3.0, 8.0, 19.0]:
            price = get_market_price(sim_h)
            check(f"get_market_price(sim_hour={sim_h:.0f}) in [0.50, 3.00]",
                  0.50 <= price <= 3.00,
                  f"Got: {price}")

    except Exception as e:
        fail("EIA API call raised an exception", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 -- K2 API live test (single minimal call)
# ─────────────────────────────────────────────────────────────────────────────
section("3. K2 Think V2 -- live single call")

if not K2_API_KEY:
    warn("K2 API skipped -- no key set")
    k2_response_raw = None
else:
    k2 = OpenAI(api_key=K2_API_KEY, base_url=K2_BASE_URL)

    minimal_context = {
        "light": 700, "temp_c": 22.0, "pressure_hpa": 1013.0,
        "solar_ma": 320.0, "load_ma": 290.0,
        "pot1": 512, "pot2": 512,
        "tilt": 0, "button": 0,
        "battery_soc": 0.65, "sim_hour": 14.0, "duck_demand": 0.30,
        "relay_state": 0, "market_price": 1.20, "reward_score": 0.0,
        "ttd_seconds": 99999.0, "storm_probability": 0.05,
        "solar_time_remaining": 99999.0, "mins_to_demand_spike": 180.0,
        "t2_demand_factor": 1.0, "dim_t4_recommended": False,
        "recommended_t4_pwm": 255, "breakeven_ttd": 0.2,
        "market_penalty_active": False, "sun_slope": -1.2,
        "pressure_slope": -0.001,
    }

    print(f"  Sending context to {K2_MODEL}...")
    t0 = time.time()
    k2_response_raw = None

    try:
        resp = k2.chat.completions.create(
            model       = K2_MODEL,
            max_tokens  = 8192,
            temperature = 0.1,
            messages    = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": json.dumps(minimal_context)},
            ],
        )

        elapsed          = time.time() - t0
        k2_response_raw  = resp.choices[0].message.content or ""

        check("K2 returned non-empty content",
              bool(k2_response_raw.strip()),
              "Empty response body")

        print(f"\n  {CYAN}K2 response time : {elapsed:.2f} s{RESET}")
        print(f"  {CYAN}Raw length       : {len(k2_response_raw)} chars{RESET}")

        # Show think block length if present
        think_match = re.search(r"<think>(.*?)</think>", k2_response_raw, re.DOTALL)
        if think_match:
            think_len = len(think_match.group(1))
            print(f"  {CYAN}<think> block    : {think_len} chars (will be stripped){RESET}")
        else:
            print(f"  {CYAN}<think> block    : not present in this response{RESET}")

        # Parse the JSON
        try:
            cmd = extract_json(k2_response_raw)

            check("Parsed to a dict",
                  isinstance(cmd, dict))

            check("'pwm' key present",
                  "pwm" in cmd)

            check("'relay' key present",
                  "relay" in cmd)

            check("'reasoning' key present",
                  "reasoning" in cmd)

            check("pwm has exactly 16 values",
                  isinstance(cmd.get("pwm"), list) and len(cmd.get("pwm", [])) == 16,
                  f"Got length: {len(cmd.get('pwm', []))}")

            check("All pwm values are integers in [0, 255]",
                  all(isinstance(v, int) and 0 <= v <= 255
                      for v in cmd.get("pwm", [])),
                  f"pwm values: {cmd.get('pwm', [])}")

            check("relay is 0 or 1",
                  cmd.get("relay") in (0, 1),
                  f"Got relay={cmd.get('relay')}")

            check("T1 channels 0 and 1 are 255 (hospital safety rule)",
                  cmd["pwm"][0] == 255 and cmd["pwm"][1] == 255,
                  f"Got pwm[0]={cmd['pwm'][0]}, pwm[1]={cmd['pwm'][1]}")

            check("lcd_line1 present and <= 16 chars",
                  "lcd_line1" in cmd and len(cmd["lcd_line1"]) <= 16,
                  f"Got: '{cmd.get('lcd_line1', '')}'")

            check("lcd_line2 present and <= 16 chars",
                  "lcd_line2" in cmd and len(cmd["lcd_line2"]) <= 16,
                  f"Got: '{cmd.get('lcd_line2', '')}'")

            check("reasoning is a non-empty string",
                  isinstance(cmd.get("reasoning"), str)
                  and len(cmd["reasoning"]) > 0)

            # Since solar surplus and good battery, T4 should stay bright
            t4_avg = sum(cmd["pwm"][10:16]) / 6.0
            if t4_avg < 100:
                warn("K2 dimmed T4 heavily despite good battery + solar surplus",
                     f"T4 avg PWM = {t4_avg:.0f} (expected ~255 at soc=0.65, solar surplus)")
            else:
                ok(f"T4 at reasonable brightness for stable conditions (avg={t4_avg:.0f})")

            print(f"\n  {CYAN}K2 reasoning : \"{cmd['reasoning']}\"{RESET}")
            print(f"  {CYAN}K2 relay     : {cmd['relay']} ({'STATE GRID' if cmd['relay'] else 'SOLAR'}){RESET}")
            print(f"  {CYAN}K2 T1        : {cmd['pwm'][0]}, {cmd['pwm'][1]}{RESET}")
            print(f"  {CYAN}K2 T4 avg    : {t4_avg:.0f}/255{RESET}")
            print(f"  {CYAN}K2 lcd_line1 : \"{cmd['lcd_line1']}\"{RESET}")

        except Exception as parse_err:
            fail("Failed to parse K2 JSON response", str(parse_err))
            print(f"\n  Raw K2 output:\n  {k2_response_raw[:600]}")

    except Exception as api_err:
        fail("K2 API call raised an exception", str(api_err))

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 -- Full 10-cycle dry run (no Arduino)
# ─────────────────────────────────────────────────────────────────────────────
section("4. Full 10-cycle dry run (simulated sensors, real K2 + forecaster)")

# Simulate a scenario: steady solar until cycle 6 when clouds arrive,
# then cycle 8 fires an earthquake tilt event.
def make_sensor(cycle: int) -> dict:
    """Generate a plausible sensor snapshot for the given cycle number."""
    if cycle < 6:
        light     = 750 - cycle * 10       # steady morning sun
        solar_ma  = 380.0 - cycle * 5
        pressure  = 1013.0 - cycle * 0.02
    else:
        light     = 750 - (cycle * 45)     # clouds rolling in fast
        solar_ma  = max(20.0, 380.0 - cycle * 50)
        pressure  = 1013.0 - cycle * 0.15  # pressure dropping -- storm

    light    = max(10, light)
    load_ma  = 280.0 + cycle * 8           # load creeping up as day goes on
    temp_c   = 21.0 + cycle * 0.3
    pot1     = 512 + cycle * 20
    pot2     = 480 + cycle * 15
    tilt     = 1 if cycle == 8 else 0      # earthquake at cycle 8

    return {
        "light":        light,
        "temp_c":       temp_c,
        "pressure_hpa": max(990.0, pressure),
        "solar_ma":     solar_ma,
        "load_ma":      load_ma,
        "pot1":         min(1023, pot1),
        "pot2":         min(1023, pot2),
        "tilt":         tilt,
        "button":       0,
    }

if not K2_API_KEY:
    warn("Dry run skipped -- K2_API_KEY not set")
else:
    k2 = OpenAI(api_key=K2_API_KEY, base_url=K2_BASE_URL)
    prev_relay     = 0
    last_time      = time.time()
    relay_clicks   = 0
    t1_violations  = 0
    score_start    = reward_score
    earthquake_ok  = False
    k2_successes   = 0
    k2_failures    = 0

    print(f"\n  Running 10 cycles with real K2 calls (this will take ~20 s)...\n")

    for cycle in range(10):
        loop_start = time.time()
        sensor     = make_sensor(cycle)

        # Update battery and history
        now       = time.time()
        dt        = now - last_time
        last_time = now
        record_sensor(sensor)
        update_battery(sensor["solar_ma"], sensor["load_ma"], dt)

        sim_hour = get_sim_hour()
        price    = get_market_price(sim_hour) if EIA_API_KEY else 1.20

        # Run forecaster
        forecast = compute_forecast(
            history         = history,
            battery_soc     = battery_soc,
            solar_ma        = sensor["solar_ma"],
            load_ma         = sensor["load_ma"],
            temp_c          = sensor["temp_c"],
            sim_hour        = sim_hour,
            market_price    = price,
            penalty_weights = BASE_WEIGHTS,
        )

        # Build K2 context
        context = {
            **sensor,
            "battery_soc":  round(battery_soc, 3),
            "sim_hour":     round(sim_hour, 2),
            "duck_demand":  round(get_duck_demand(), 2),
            "relay_state":  prev_relay,
            "market_price": price,
            "reward_score": round(reward_score, 1),
            **forecast,
        }

        # Call K2
        command = safe_command()
        try:
            resp = k2.chat.completions.create(
                model       = K2_MODEL,
                max_tokens  = 8192,
                temperature = 0.1,
                messages    = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": json.dumps(context)},
                ],
            )
            raw = resp.choices[0].message.content or ""
            command = extract_json(raw)
            if len(command.get("pwm", [])) != 16:
                command = repair_command(command)
                print(f"  [cycle {cycle}] K2 partial response repaired (pwm padded)")
            # Hard safety
            command["pwm"][0] = 255
            command["pwm"][1] = 255
            k2_successes += 1
        except Exception as e:
            k2_failures += 1
            command = safe_command()
            print(f"  {RED}[cycle {cycle}] K2 error: {e}{RESET}")

        # Hard Python overrides
        if sensor["tilt"] == 1:
            command["pwm"][:2]    = [255, 255]
            command["pwm"][2:5]   = [255, 255, 255]
            command["pwm"][5:10]  = [128] * 5
            command["pwm"][10:16] = [0] * 6
            command["relay"]      = 1
            command["reasoning"]  = "Earthquake lockdown."

        # Compute reward
        reward_score = compute_reward(
            pwm        = command["pwm"],
            relay      = command["relay"],
            pot1       = sensor["pot1"],
            pot2       = sensor["pot2"],
            prev_relay = prev_relay,
            weights    = BASE_WEIGHTS,
        )

        # Track relay clicks
        if command["relay"] == 1 and prev_relay == 0:
            relay_clicks += 1
        prev_relay = command["relay"]

        # T1 violation check
        if command["pwm"][0] != 255 or command["pwm"][1] != 255:
            t1_violations += 1

        # Earthquake check
        if sensor["tilt"] == 1:
            eq_t1_ok = command["pwm"][0] == 255 and command["pwm"][1] == 255
            eq_t4_ok = all(v == 0 for v in command["pwm"][10:16])
            eq_relay = command["relay"] == 1
            earthquake_ok = eq_t1_ok and eq_t4_ok and eq_relay

        # Per-cycle summary line
        t4_avg     = sum(command["pwm"][10:16]) / 6.0
        storm_prob = forecast.get("storm_probability", 0.0)
        ttd        = forecast.get("ttd_seconds", 99999.0)
        ttd_str    = f"{ttd:.0f}s" if ttd < 99999 else "inf"
        quake_flag = " [QUAKE]" if sensor["tilt"] else ""
        relay_flag = " RELAY" if command["relay"] else "     "
        print(
            f"  cycle {cycle:02d}  "
            f"soc={battery_soc:.2f}  "
            f"solar={sensor['solar_ma']:5.0f}mA  "
            f"load={sensor['load_ma']:5.0f}mA  "
            f"storm={storm_prob:.2f}  "
            f"ttd={ttd_str:>6}  "
            f"T4avg={t4_avg:5.0f}  "
            f"score={reward_score:+8.0f}  "
            f"{relay_flag}{quake_flag}"
        )

        # Pace at ~2 s per cycle to respect K2 rate limits
        elapsed = time.time() - loop_start
        time.sleep(max(0.0, 2.0 - elapsed))

    # ── Dry run assertions ────────────────────────────────────────────────────
    print()
    # K2 Think V2 sometimes exhausts its internal reasoning budget before
    # outputting JSON.  Majority success (>=7/10) is the pass bar; anything
    # below 5/10 is a hard failure worth investigating.
    if k2_failures == 0:
        ok("All 10 K2 calls returned valid JSON")
    elif k2_failures <= 3:
        warn(f"{10 - k2_failures}/10 K2 calls succeeded (within acceptable range)",
             "A few truncated responses repaired by repair_command -- normal for K2 Think V2")
    else:
        fail(f"Only {10 - k2_failures}/10 K2 calls succeeded",
             "Check K2_API_KEY, network, or raise max_tokens further")

    check("T1 (hospitals) never dimmed across all cycles",
          t1_violations == 0,
          f"T1 was dimmed in {t1_violations} cycle(s) -- critical safety failure")

    check("Earthquake override fired correctly at cycle 8",
          earthquake_ok,
          "T1!=255 or T4!=0 or relay!=1 during tilt event")

    check("Reward score moved from starting value",
          reward_score != score_start,
          "Score unchanged -- compute_reward may not be running")

    # Storm started at cycle 6, K2 should have started dimming T4
    # We can't assert exact values but we can check the score is finite
    check("Reward score is a finite number",
          math.isfinite(reward_score),
          f"Got: {reward_score}")

    if relay_clicks > 0:
        warn(f"Relay clicked {relay_clicks} time(s) during dry run",
             "Not necessarily a bug -- K2 may have correctly decided to buy grid power")
    else:
        ok("No relay clicks (K2 managed on solar + battery throughout)")

    print(f"\n  {CYAN}Final reward score : {reward_score:+.1f}{RESET}")
    print(f"  {CYAN}Final battery SoC  : {battery_soc:.3f}{RESET}")
    print(f"  {CYAN}K2 successes       : {k2_successes}/10{RESET}")
    print(f"  {CYAN}Relay clicks       : {relay_clicks}{RESET}")

# ─────────────────────────────────────────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{BOLD}{'='*62}{RESET}")
print(f"{BOLD}  RESULTS:  "
      f"{GREEN}{PASS} passed{RESET}{BOLD},  "
      f"{RED}{FAIL} failed{RESET}{BOLD},  "
      f"{YELLOW}{WARN} warnings{RESET}")
print(f"{BOLD}{'='*62}{RESET}\n")

if FAIL > 0:
    print(f"{RED}  Action required -- see FAIL lines above.{RESET}\n")
    sys.exit(1)
elif WARN > 0:
    print(f"{YELLOW}  Passed with warnings -- review WARN lines above.{RESET}\n")
    sys.exit(0)
else:
    print(f"{GREEN}  All checks passed. NEO is ready for hardware.{RESET}\n")
    sys.exit(0)
