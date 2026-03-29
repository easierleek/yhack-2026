#!/usr/bin/env python3
"""
NEO — Nodal Energy Oracle
Combined HTTP + WebSocket server for Railway deployment.
Serves the React frontend as static files and provides real-time state via WebSocket.
"""

import os
import json
import math
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
    'reasoning': 'Grid stable. Solar generation nominal. All tiers online.',
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


# ─── Simulation loop (advances time and solar generation) ────────────────────

def _sim_loop() -> None:
    tick = 0
    while True:
        tick += 1
        with _state_lock:
            h = _state['sim_hour']
            h = (h + 1 / 1800) % 24          # 1 sim-hour ≈ 30 real minutes
            _state['sim_hour'] = h

            # Solar bell curve: 6 AM – 6 PM
            raw_solar = max(0.0, 520 * math.sin(math.pi * max(0, h - 6) / 12)) if 6 < h < 18 else 0.0
            jitter = math.sin(tick * 0.37) * 12
            solar = max(0.0, raw_solar + jitter)
            _state['solar_ma'] = round(solar, 1)
            _state['light'] = int(min(1023, solar * 1.96))

            # Relay: grid assist when solar can't cover load
            _state['relay'] = 1 if solar < _state['load_ma'] * 0.8 else 0

            # Battery charges during solar surplus
            soc = _state['battery_soc']
            surplus = solar - _state['load_ma']
            soc += surplus * 0.000002
            _state['battery_soc'] = round(max(0.05, min(1.0, soc)), 4)

            _state['duck_demand'] = round(0.5 + 0.3 * math.sin(math.pi * h / 12), 3)
            payload = json.dumps(_state)

        _broadcast(payload)
        time.sleep(1)


threading.Thread(target=_sim_loop, daemon=True, name='neo-sim').start()


# ─── HTTP API ─────────────────────────────────────────────────────────────────

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'mode': 'simulation', 'clients': len(_clients)})


@app.route('/api/hardware/update', methods=['POST'])
def hardware_update():
    """
    Update a node's power level from hardware (Arduino / external trigger).

    Body: { "nodeId": "yale-new-haven", "percentage": 45, "status": "online" }
    """
    data = request.get_json(silent=True) or {}
    node_id = data.get('nodeId', '')
    percentage = data.get('percentage')
    status = data.get('status', 'online')

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
        _state['reasoning'] = f'Mayor directive applied: {directive}'
        payload = json.dumps(_state)

    _broadcast(payload)
    return jsonify({'status': 'ok', 'strategy': strategy, 'directive': directive,
                    'response': f'NEO: Directive received. Strategy: {strategy}.'})


@app.route('/api/pwm/set', methods=['POST'])
def set_pwm():
    data = request.get_json(silent=True) or {}
    pwm_values = data.get('pwm', [])
    relay = data.get('relay', 0)
    if len(pwm_values) != 16:
        return jsonify({'error': 'pwm must have exactly 16 values'}), 400
    with _state_lock:
        _state['pwm'] = [int(v) for v in pwm_values]
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
    print(f'[NEO] Server starting on http://0.0.0.0:{port}')
    print(f'[NEO] WebSocket available at ws://0.0.0.0:{port}/ws')
    print(f'[NEO] Static frontend: {STATIC}')
    app.run(host='0.0.0.0', port=port, threaded=True)
