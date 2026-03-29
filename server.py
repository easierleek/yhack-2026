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

STATIC = os.path.join(os.path.dirname(__file__), 'frontend', 'web', 'dist')

app = Flask(__name__, static_folder=STATIC, static_url_path='')
CORS(app)
sock = Sock(app)

# ─── Shared state (mirrors NeoState TypeScript type) ─────────────────────────

_state_lock = threading.Lock()
_state = {
    'battery_soc': 0.62,
    'sim_hour': 9.0,
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

def _find_arduino_port() -> str | None:
    candidates = (
        glob.glob('/dev/cu.usbmodem*') +
        glob.glob('/dev/ttyACM*') +
        glob.glob('/dev/ttyUSB*')
    )
    return candidates[0] if candidates else None


# ─── Arduino telemetry parser ────────────────────────────────────────────────

def _parse_arduino_line(line: str) -> dict | None:
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
            light    = int(min(1023, (v_out / 5.0) * 1023))
            return {
                'format':       'A',
                'v_out':        v_out,
                'v_drop':       v_drop,
                'current_a':    current,
                'power_w':      power,
                'load_ma':      load_ma,
                'light':        light,
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
                    'solar_ma':     float(parts[3]),
                    'load_ma':      float(parts[4]),
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

    import datetime as _dt

    # Try 115200 first (actual deployed firmware), fall back to 9600 (.ino firmware)
    for baud in (115200, 9600):
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
                    load_ma  = parsed['load_ma']
                    light    = parsed['light']
                    _state['load_ma'] = load_ma
                    _state['light']   = light
                    # solar_ma: keep simulation value (no dedicated solar sensor in this fw)
                    solar_ma = _state['solar_ma']
                    _state['relay'] = 1 if load_ma > solar_ma * 0.8 else 0

                else:   # fmt == 'B'
                    _state['light']        = parsed['light']
                    _state['temp_c']       = parsed['temp_c']
                    _state['pressure_hpa'] = parsed['pressure_hpa']
                    _state['solar_ma']     = parsed['solar_ma']
                    _state['load_ma']      = parsed['load_ma']
                    _state['pot1']         = parsed['pot1']
                    _state['pot2']         = parsed['pot2']
                    _state['tilt']         = parsed['tilt']
                    _state['button']       = parsed['button']
                    solar_ma = parsed['solar_ma']
                    load_ma  = parsed['load_ma']
                    _state['relay'] = 1 if solar_ma < load_ma * 0.8 else 0

                # Real-time clock → sim_hour
                now = _dt.datetime.now()
                _state['sim_hour'] = round(now.hour + now.minute / 60, 2)

                # Drift battery SOC
                surplus = _state['solar_ma'] - _state['load_ma']
                soc = max(0.05, min(1.0, _state['battery_soc'] + surplus * 0.0000005))
                _state['battery_soc'] = round(soc, 4)

                payload = json.dumps(_state)

            _broadcast(payload)

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
    tick = 0
    while True:
        if _arduino_connected:
            time.sleep(1)
            tick += 1
            continue

        tick += 1
        with _state_lock:
            h = _state['sim_hour']
            h = (h + 1 / 1800) % 24
            _state['sim_hour'] = h

            raw_solar = max(0.0, 520 * math.sin(math.pi * max(0, h - 6) / 12)) if 6 < h < 18 else 0.0
            jitter = math.sin(tick * 0.37) * 12
            solar = max(0.0, raw_solar + jitter)
            _state['solar_ma'] = round(solar, 1)
            _state['light']    = int(min(1023, solar * 1.96))
            _state['relay']    = 1 if solar < _state['load_ma'] * 0.8 else 0

            soc = _state['battery_soc']
            surplus = solar - _state['load_ma']
            soc = max(0.05, min(1.0, soc + surplus * 0.000002))
            _state['battery_soc']  = round(soc, 4)
            _state['duck_demand']  = round(0.5 + 0.3 * math.sin(math.pi * h / 12), 3)
            _state['reasoning']    = 'Simulation mode — no Arduino connected'
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


@app.route('/api/mayor-directive', methods=['POST'])
def mayor_directive():
    data = request.get_json(silent=True) or {}
    directive = data.get('directive', '')
    dl = directive.lower()

    with _state_lock:
        if any(w in dl for w in ['off', 'shutdown', 'emergency', 'cut', 'blackout']):
            _state['pwm'] = [255, 255, 51, 51, 51, 51, 51, 51, 51, 51, 0, 0, 0, 0, 0, 0]
            strategy = 'REDUCE'
            _state['fault'] = 'EMERGENCY LOAD SHED ACTIVE'
        elif any(w in dl for w in ['reduce', 'save', 'conserve', 'dim']):
            _state['pwm'] = [255, 255, 204, 204, 204, 153, 153, 153, 153, 153, 77, 77, 77, 77, 77, 77]
            strategy = 'REDUCE'
            _state['fault'] = ''
        elif any(w in dl for w in ['on', 'maximize', 'full', 'max', 'increase', 'restore']):
            _state['pwm'] = [255] * 16
            strategy = 'INCREASE'
            _state['fault'] = ''
        else:
            _state['pwm'] = [255, 255, 255, 255, 255,
                             200, 200, 200, 200, 200,
                             128, 128, 128, 128, 128, 128]
            strategy = 'BALANCED'
            _state['fault'] = ''

        _state['active_policy'] = directive[:60] if directive else 'None'
        _state['reasoning']     = f'Mayor directive: {directive}'
        payload = json.dumps(_state)

    _broadcast(payload)
    return jsonify({'status': 'ok', 'strategy': strategy, 'directive': directive,
                    'response': f'NEO: Directive received. Strategy: {strategy}.'})


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
