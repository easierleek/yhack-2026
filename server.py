#!/usr/bin/env python3
"""
NEO — Nodal Energy Oracle
Combined HTTP + WebSocket server for local and Railway deployment.

Local:   reads live Arduino data via USB serial
Railway: falls back to simulation loop (no hardware)
"""

import glob
import json
import math
import os
import threading
import time
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_sock import Sock

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

STATIC = os.path.join(os.path.dirname(__file__), 'frontend', 'web', 'dist')

app = Flask(__name__)
CORS(app)
sock = Sock(app)

# ─── Shared state (mirrors NeoState TypeScript type) ─────────────────────────

_state_lock = threading.Lock()
_state = {
    'battery_soc': 0.62,
    'sim_hour': 6.5,
    'market_price': 0.17,
    'relay': 0,
    'reward_score': 0.81,
    'light': 620,
    'temp_c': 21.5,
    'pressure_hpa': 1013.25,
    'solar_ma': 380.0,
    'load_ma': 290.0,
    'pot1': 512,
    'pot2': 512,
    'tilt': 0,
    'button': 0,
    'sun_slope': 0.02,
    'pressure_slope': 0.0,
    'duck_demand': 0.48,
    'storm_probability': 0.05,
    'ttd_seconds': 99999,
    'solar_time_remaining': 32400,
    't2_demand_factor': 1.0,
    'breakeven_ttd': 0,
    'market_penalty_active': False,
    'dim_t4_recommended': False,
    'recommended_t4_pwm': 255,
    'mins_to_demand_spike': 9999,
    'pwm': [255, 255, 255, 255, 255,
            200, 200, 200, 200, 200,
            128, 128, 128, 128, 128, 128],
    'reasoning': 'Waiting for Arduino...',
    'reasoning_feed': [],
    'eia_retail': 0.17,
    'eia_demand_mw': 402000.0,
    'eia_live': False,
    'eia_age_s': 0.0,
    'active_policy': 'None',
    'active_policies': [],
    'policy_expires_in': 0,
    'policy_real_expires': 0,
    'fault': '',
    'loop_ms': 50.0,
    'k2_calls': 0,
}

_arduino_connected = False
_policy_lock_until = 0.0   # epoch time; sim won't touch PWM until after this

# ─── Dynamic PWM model ───────────────────────────────────────────────────────

def _compute_pwm(solar_ma: float, load_ma: float, battery_soc: float, sim_hour: float, light: int = 512, res_factor: float = 1.0, com_factor: float = 1.0) -> list:
    """
    Distribute power across tiers based on available supply.

    Priority order: T1 (hospitals) → T2 (utilities) → T3 (residential) → T4 (commercial).
    T4 is shed first; T1 is never reduced below ~75%.

    power_score: 0.0 = night/crisis  1.5 = peak solar+full battery
    """
    # Normalize solar to 0-1 (peak ~520 mA at noon)
    solar_avail = min(1.0, solar_ma / 520.0)
    # Light sensor 0-1023 also contributes (blended with solar)
    light_avail = min(1.0, light / 1023.0)
    # Combined score: average of solar + light drives the model, battery adds baseload
    power_score = (solar_avail * 0.6 + light_avail * 0.4) + battery_soc * 0.5

    # Duck-curve evening demand spike (17-21h) reduces effective score
    if 17 <= sim_hour <= 21:
        power_score *= 0.75

    # Each tier covers a different range of power_score
    t1 = int(min(255, 190 + power_score * 43))                           # 190-255  (75-100%)
    t2 = int(min(255, max(80,  110 + power_score * 95)))                 # 80-252   (31-99%)
    t3 = int(min(255, max(0,   power_score * 185 * res_factor)))         # knob A scales residential
    t4 = int(min(255, max(0,   (power_score - 0.35) * 220 * com_factor)))# knob B scales commercial

    return [
        t1, t1,                   # ch 0-1   T1 Hospitals
        t2, t2, t2,               # ch 2-4   T2 Utilities
        t3, t3, t3, t3, t3,       # ch 5-9   T3 Residential
        t4, t4, t4, t4, t4, t4,  # ch 10-15 T4 Commercial
    ]

# ─── K2 AI client ────────────────────────────────────────────────────────────

_k2_client = None
_k2_key = os.environ.get('K2_API_KEY', '')
if _k2_key:
    try:
        from openai import OpenAI as _OpenAI
        _k2_client = _OpenAI(api_key=_k2_key, base_url='https://api.k2think.ai/v1')
        print(f'[K2] AI client ready')
    except Exception as _e:
        print(f'[K2] Init failed: {_e}')
else:
    print('[K2] No K2_API_KEY — using rule-based responses')

# Infrastructure node id → PWM channel (mirrors infrastructure.ts)
NODE_CHANNELS = {
    'yale-new-haven':   0,
    'st-raphael':       1,
    'english-station':  2,
    'harbor-sub':       3,
    'westville-res':    5,
    'dixwell-res':      6,
    'fair-haven-res':   7,
    'east-rock':        8,
    'wooster-square':   9,
    'downtown-com':     10,
    'whalley-corridor': 11,
}

# ─── WebSocket client registry ───────────────────────────────────────────────

_clients_lock = threading.Lock()
_clients: set = set()


def _broadcast(payload: str) -> None:
    dead: set = set()
    with _clients_lock:
        targets = set(_clients)
    for ws in targets:
        try:
            ws.send(payload)
        except Exception:
            dead.add(ws)
    if dead:
        with _clients_lock:
            _clients.difference_update(dead)


@sock.route('/ws')
def ws_handler(ws):
    with _clients_lock:
        _clients.add(ws)
    try:
        with _state_lock:
            ws.send(json.dumps(_state))
        while True:
            try:
                ws.receive(timeout=30)
            except Exception:
                break
    finally:
        with _clients_lock:
            _clients.discard(ws)


# ─── Arduino auto-detect ─────────────────────────────────────────────────────

def _find_arduino_port():
    candidates = (
        glob.glob('/dev/cu.usbmodem*') +
        glob.glob('/dev/ttyACM*') +
        glob.glob('/dev/ttyUSB*')
    )
    return candidates[0] if candidates else None


# ─── Arduino telemetry parser ────────────────────────────────────────────────

def _parse_arduino_line(line: str):
    """
    Parse either telemetry format the Arduino may send:

    Format A (V_IN/CURRENT style — actual deployed firmware @ 115200):
      'V_IN: 5.0V | V_OUT: 4.28V | V_DROP: 0.71V || CURRENT: 0.028A | POWER: 0.12W'

    Format B (CSV — firmware from .ino file @ 9600):
      'light,temp_c,pressure_hpa,solar_ma,load_ma,pot1,pot2,tilt,button'
    """
    import re

    # ── Format A ──────────────────────────────────────────────────────────────
    if 'V_IN' in line and 'CURRENT' in line:
        try:
            v_out    = float(re.search(r'V_OUT:\s*([\d.]+)', line).group(1))
            v_drop   = float(re.search(r'V_DROP:\s*([\d.]+)', line).group(1))
            current  = float(re.search(r'CURRENT:\s*([\d.]+)', line).group(1))
            power    = float(re.search(r'POWER:\s*([\d.]+)', line).group(1))
            load_ma  = round(current * 1000, 2)       # A → mA
            # Estimate light from V_OUT (higher output = brighter LEDs = more "solar" in demo)
            return {
                'format':    'A',
                'v_out':     v_out,
                'v_drop':    v_drop,
                'current_a': current,
                'power_w':   power,
                'load_ma':   load_ma,
            }
        except Exception:
            return None

    # ── Format B ──────────────────────────────────────────────────────────────
    if ',' in line:
        parts = line.split(',')
        if len(parts) >= 9:
            try:
                return {
                    'format':       'B',
                    'light':        int(float(parts[0])),
                    'temp_c':       float(parts[1]),
                    'pressure_hpa': float(parts[2]),
                    'solar_ma':     float(parts[3]) if parts[3].strip().lower() != 'nan' else 0.0,
                    'load_ma':      float(parts[4]) if parts[4].strip().lower() != 'nan' else 0.0,
                    'pot1':         int(float(parts[5])),
                    'pot2':         int(float(parts[6])),
                    'tilt':         int(float(parts[7])),
                    'button':       int(float(parts[8])),
                }
            except (ValueError, IndexError):
                return None

    return None


# ─── Arduino reader (runs when hardware is present) ──────────────────────────

def _arduino_loop(port: str) -> None:
    global _arduino_connected
    try:
        import serial as _serial
    except ImportError:
        print('[ARDUINO] pyserial not installed — pip install pyserial')
        return

    # Try 115200 first (actual deployed firmware), fall back to 9600 (.ino firmware)
    for baud in (9600, 115200):
        ser = None
        try:
            ser = _serial.Serial(port, baud, timeout=2.0)
            time.sleep(2)
            # Read a probe line to confirm the baud rate
            for _ in range(5):
                probe = ser.readline().decode('utf-8', errors='replace').strip()
                if _parse_arduino_line(probe):
                    print(f'[ARDUINO] Connected on {port} @ {baud} baud')
                    break
            else:
                ser.close()
                continue
            break           # found working baud
        except Exception as exc:
            print(f'[ARDUINO] {baud} baud failed: {exc}')
            if ser:
                try:
                    ser.close()
                except Exception:
                    pass
            ser = None
    else:
        print('[ARDUINO] Could not establish communication — staying in simulation')
        return

    _arduino_connected = True
    with _state_lock:
        _state['reasoning'] = f'Arduino live on {port}'
    _broadcast(json.dumps(_state))

    _last_broadcast = 0.0   # throttle: broadcast at most once per second

    while True:
        try:
            line = ser.readline().decode('utf-8', errors='replace').strip()
            if not line:
                continue
            parsed = _parse_arduino_line(line)
            if not parsed:
                continue

            with _state_lock:
                fmt = parsed['format']

                if fmt == 'A':
                    power_w = parsed['power_w']
                    # sim_loop owns load_ma, relay, pwm — only update temp here
                    _state['temp_c']       = round(20.0 + power_w * 40, 1)
                    _state['pressure_hpa'] = 1013.25

                else:   # fmt == 'B'
                    # arduino_loop owns ONLY physical sensor readings.
                    # sim_loop owns solar_ma, load_ma, relay, pwm — don't touch them here.
                    _state['light']        = parsed['light']
                    _state['temp_c']       = parsed['temp_c']
                    _state['pressure_hpa'] = parsed['pressure_hpa']
                    _state['pot1']         = parsed['pot1']
                    _state['pot2']         = parsed['pot2']
                    _state['tilt']         = parsed['tilt']
                    _state['button']       = parsed['button']
                    # button press: relay toggle handled by sim_loop via state

                payload = json.dumps(_state)

            # Throttle broadcasts to 1 Hz — Arduino sends 5/s which causes flicker
            now = time.time()
            if now - _last_broadcast >= 1.0:
                _broadcast(payload)
                _last_broadcast = now

        except Exception as exc:
            print(f'[ARDUINO] Lost connection: {exc}')
            _arduino_connected = False
            try:
                ser.close()
            except Exception:
                pass
            time.sleep(3)
            # Re-enter the outer function to attempt reconnect
            _arduino_loop(port)
            return


# ─── Simulation loop (fallback when no Arduino is present) ───────────────────

def _sim_loop() -> None:
    global _policy_lock_until
    tick = 0
    while True:
        tick += 1

        with _state_lock:
            # Advance simulated hour regardless of Arduino (Arduino doesn't measure solar)
            h = _state['sim_hour']
            h = (h + 1 / 120) % 24   # 1 sim-hour per 2 real minutes → full day in 48 min
            _state['sim_hour'] = h

            # Solar generation: bell curve 6am–6pm
            raw_solar = max(0.0, 520 * math.sin(math.pi * max(0, h - 6) / 12)) if 6 < h < 18 else 0.0
            jitter = math.sin(tick * 0.37) * 15
            solar = max(0.0, raw_solar + jitter)
            _state['solar_ma'] = round(solar, 1)

            # City demand: base load + duck-curve evening spike + noise
            base_demand = 220 + 80 * math.sin(math.pi * (h - 6) / 18)
            eve_spike   = 60  if 17 <= h <= 21 else 0
            demand      = max(50, base_demand + eve_spike + math.sin(tick * 0.19) * 20)
            _state['load_ma'] = round(demand, 1)

            # Light: use real Arduino LDR if connected (Format B), else simulate from solar
            if not _arduino_connected:
                _state['light'] = int(min(1023, solar * 1.96))
            if not _arduino_connected:
                _state['temp_c']    = round(18 + 8 * math.sin(math.pi * (h - 6) / 12), 1)
                _state['reasoning'] = 'Simulation mode — no Arduino connected'

            _state['relay'] = 1 if solar < demand * 0.8 else 0

            soc = _state['battery_soc']
            surplus = solar - demand
            soc = max(0.05, min(1.0, soc + surplus * 0.000002))
            _state['battery_soc'] = round(soc, 4)
            _state['duck_demand'] = round(0.5 + 0.3 * math.sin(math.pi * h / 12), 3)

            # Knob modifiers: pot1 = residential demand (0-1023), pot2 = commercial demand
            res_factor = 0.5 + (_state['pot1'] / 1023.0)   # 0.5x–1.5x
            com_factor = 0.5 + (_state['pot2'] / 1023.0)   # 0.5x–1.5x

            # Recompute per-building PWM unless a mayor directive is still active
            if time.time() > _policy_lock_until:
                _state['pwm'] = _compute_pwm(solar, demand, soc, h, _state['light'],
                                             res_factor, com_factor)
                _state['active_policy'] = 'None'

            payload = json.dumps(_state)

        _broadcast(payload)
        time.sleep(1)


# ─── Start background threads ────────────────────────────────────────────────

def _start_background() -> None:
    port = _find_arduino_port()
    if port:
        print(f'[NEO] Arduino detected at {port} — starting hardware reader')
        threading.Thread(target=_arduino_loop, args=(port,), daemon=True, name='neo-arduino').start()
    else:
        print('[NEO] No Arduino found — running in simulation mode')

    threading.Thread(target=_sim_loop, daemon=True, name='neo-sim').start()


_start_background()

# ─── HTTP API ─────────────────────────────────────────────────────────────────

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'ok',
        'arduino': 'connected' if _arduino_connected else 'simulation',
        'clients': len(_clients),
    })


@app.route('/api/hardware/update', methods=['POST'])
def hardware_update():
    """
    Update a node's power level from external hardware trigger.
    Body: { "nodeId": "yale-new-haven", "percentage": 45, "status": "online" }
    """
    data = request.get_json(silent=True) or {}
    node_id    = data.get('nodeId', '')
    percentage = data.get('percentage')
    status     = data.get('status', 'online')

    channel = NODE_CHANNELS.get(node_id)
    if channel is None:
        return jsonify({'error': f'Unknown nodeId: {node_id}',
                        'valid': list(NODE_CHANNELS.keys())}), 404

    with _state_lock:
        if status == 'offline':
            _state['pwm'][channel] = 0
        elif percentage is not None:
            _state['pwm'][channel] = round(max(0, min(100, float(percentage))) / 100 * 255)
        payload = json.dumps(_state)

    _broadcast(payload)
    return jsonify({
        'status': 'ok',
        'nodeId': node_id,
        'channel': channel,
        'pwm': _state['pwm'][channel],
    })


def _k2_mayor_response(directive: str, snapshot: dict) -> str:
    """Call K2 AI for a mayor directive response. Falls back to rule-based on error."""
    if not _k2_client:
        return None
    try:
        system = (
            "You are NEO (Nodal Energy Oracle), an AI power management system for New Haven, CT.\n"
            "You respond to the mayor's power directives concisely (2-3 sentences).\n"
            "Grid tiers: T1=Hospitals (critical), T2=Utilities, T3=Residential, T4=Commercial (flexible).\n"
            "Reference real grid data in your response. Be direct and authoritative."
        )
        user = (
            f"Mayor directive: \"{directive}\"\n"
            f"Current grid state: solar={snapshot['solar_ma']:.0f}mA, "
            f"load={snapshot['load_ma']:.0f}mA, "
            f"battery={snapshot['battery_soc']*100:.0f}%, "
            f"relay={'GRID' if snapshot['relay'] else 'SOLAR'}, "
            f"T1_pwm={snapshot['pwm'][0]}, T4_pwm={snapshot['pwm'][10]}\n"
            "Acknowledge the directive and explain what NEO is doing."
        )
        resp = _k2_client.chat.completions.create(
            model='MBZUAI-IFM/K2-Think-v2',
            messages=[{'role': 'system', 'content': system},
                      {'role': 'user', 'content': user}],
            max_tokens=120,
            temperature=0.7,
        )
        text = resp.choices[0].message.content.strip()
        # Strip <think>...</think> reasoning block if present
        if '</think>' in text:
            text = text.split('</think>', 1)[-1].strip()
        with _state_lock:
            _state['k2_calls'] += 1
        return text
    except Exception as exc:
        print(f'[K2] API error: {exc}')
        return None


@app.route('/api/mayor-directive', methods=['POST'])
def mayor_directive():
    data = request.get_json(silent=True) or {}
    directive = data.get('directive', '')
    dl = directive.lower()

    # Detect which tier is targeted
    commercial = any(w in dl for w in ['commercial', 't4', 'whalley', 'wooster', 'downtown'])
    residential = any(w in dl for w in ['residential', 't3', 'westville', 'dixwell', 'fair haven', 'east rock'])
    hospital = any(w in dl for w in ['hospital', 't1', 'yale', 'raphael', 'critical'])
    utility = any(w in dl for w in ['utility', 't2', 'english', 'harbor', 'substation'])
    increase = any(w in dl for w in ['increase', 'boost', 'more', 'maximize', 'full', 'max', 'on', 'restore', 'raise'])
    reduce = any(w in dl for w in ['reduce', 'cut', 'lower', 'dim', 'save', 'conserve', 'less', 'shed'])
    emergency = any(w in dl for w in ['emergency', 'shutdown', 'blackout', 'off'])

    with _state_lock:
        pwm = list(_state['pwm'])  # start from current values

        if emergency:
            # Emergency: protect T1, shed T4 entirely, halve T3
            pwm = [255, 255, 51, 51, 51, 51, 51, 51, 51, 51, 0, 0, 0, 0, 0, 0]
            strategy = 'EMERGENCY'
            _state['fault'] = 'EMERGENCY LOAD SHED ACTIVE'

        elif increase and commercial:
            # Boost T4, rob from T3 to compensate
            pwm[10:16] = [230] * 6   # T4 commercial → high
            pwm[5:10]  = [120] * 5   # T3 residential → reduced
            strategy = 'BOOST_COMMERCIAL'
            _state['fault'] = ''

        elif increase and residential:
            # Boost T3, rob from T4
            pwm[5:10]  = [230] * 5   # T3 residential → high
            pwm[10:16] = [80]  * 6   # T4 commercial → reduced
            strategy = 'BOOST_RESIDENTIAL'
            _state['fault'] = ''

        elif increase and hospital:
            # Max T1, pull from T3+T4
            pwm[0:2]   = [255] * 2   # T1 → max
            pwm[5:10]  = [140] * 5   # T3 → reduced
            pwm[10:16] = [60]  * 6   # T4 → low
            strategy = 'BOOST_CRITICAL'
            _state['fault'] = ''

        elif reduce and commercial:
            # Shed T4
            pwm[10:16] = [40] * 6
            strategy = 'SHED_COMMERCIAL'
            _state['fault'] = ''

        elif reduce and residential:
            # Dim T3, protect T1
            pwm[5:10]  = [100] * 5
            strategy = 'SHED_RESIDENTIAL'
            _state['fault'] = ''

        elif reduce:
            # General reduction: protect T1, step down T2→T3→T4
            pwm = [255, 255, 200, 200, 200, 140, 140, 140, 140, 140, 60, 60, 60, 60, 60, 60]
            strategy = 'REDUCE'
            _state['fault'] = ''

        elif increase:
            # General increase: step up all tiers proportionally
            pwm = [255, 255, 255, 255, 255, 220, 220, 220, 220, 220, 180, 180, 180, 180, 180, 180]
            strategy = 'INCREASE'
            _state['fault'] = ''

        else:
            # Balanced fallback
            pwm = [255, 255, 255, 255, 255, 200, 200, 200, 200, 200, 128, 128, 128, 128, 128, 128]
            strategy = 'BALANCED'
            _state['fault'] = ''

        _state['pwm'] = pwm

        _state['active_policy'] = directive[:60] if directive else 'None'
        _state['reasoning']     = f'Mayor directive: {directive}'
        snapshot = dict(_state)
        payload = json.dumps(_state)

    # Lock sim from overriding PWM for 2 minutes
    global _policy_lock_until
    _policy_lock_until = time.time() + 120

    _broadcast(payload)

    # Call K2 AI for response (outside lock — may take a second)
    ai_text = _k2_mayor_response(directive, snapshot)
    response_text = ai_text if ai_text else f'NEO: Directive received. Strategy: {strategy}. Adjusting grid allocation.'

    return jsonify({'status': 'ok', 'strategy': strategy, 'directive': directive,
                    'response': response_text})


@app.route('/api/pwm/set', methods=['POST'])
def set_pwm():
    data = request.get_json(silent=True) or {}
    pwm_values = data.get('pwm', [])
    relay      = data.get('relay', 0)
    if len(pwm_values) != 16:
        return jsonify({'error': 'pwm must have exactly 16 values'}), 400
    with _state_lock:
        _state['pwm']   = [int(v) for v in pwm_values]
        _state['relay'] = relay
        payload = json.dumps(_state)
    _broadcast(payload)
    return jsonify({'status': 'ok'})


@app.route('/api/state')
def get_state():
    with _state_lock:
        return jsonify(dict(_state))


# ─── Static frontend (catch-all SPA route) ───────────────────────────────────

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def spa(path):
    if path and os.path.exists(os.path.join(STATIC, path)):
        return send_from_directory(STATIC, path)
    return send_from_directory(STATIC, 'index.html')


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8765))
    print(f'[NEO] Server on http://0.0.0.0:{port}')
    print(f'[NEO] WebSocket at ws://0.0.0.0:{port}/ws')
    print(f'[NEO] Static frontend: {STATIC}')
    app.run(host='0.0.0.0', port=port, threaded=True)
