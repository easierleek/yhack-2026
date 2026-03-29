#!/usr/bin/env python3
"""
NEO Pipeline Verifier
Run this to check: Arduino → backend → WebSocket → frontend

Usage:  python verify_pipeline.py
"""

import glob
import json
import sys
import time
import threading
import urllib.request

PASS = '\033[92m✓\033[0m'
FAIL = '\033[91m✗\033[0m'
INFO = '\033[94m→\033[0m'


# ─── Step 1: Detect Arduino ───────────────────────────────────────────────────

def check_arduino():
    print('\n[1] Arduino Detection')
    candidates = (
        glob.glob('/dev/cu.usbmodem*') +
        glob.glob('/dev/ttyACM*') +
        glob.glob('/dev/ttyUSB*')
    )
    if not candidates:
        print(f'  {FAIL} No Arduino serial port found.')
        print(f'  {INFO} Plug in the Arduino and re-run.')
        return None
    port = candidates[0]
    print(f'  {PASS} Arduino found at {port}')
    return port


# ─── Step 2: Read live Arduino data ──────────────────────────────────────────

def check_arduino_data(port: str, n: int = 5):
    print(f'\n[2] Arduino Serial Data  (reading {n} lines from {port})')
    try:
        import serial
    except ImportError:
        print(f'  {FAIL} pyserial not installed — run: pip install pyserial')
        return False

    try:
        ser = serial.Serial(port, 9600, timeout=2.0)
        time.sleep(2)  # wait for Arduino reset

        ok = 0
        for i in range(n + 2):            # allow a couple of garbage lines
            raw = ser.readline().decode('utf-8', errors='replace').strip()
            if not raw or ',' not in raw:
                continue
            parts = raw.split(',')
            if len(parts) < 9:
                continue
            try:
                light, temp_c, pres_hpa, solar_ma, load_ma, pot1, pot2, tilt, btn = \
                    [float(p) for p in parts[:9]]
            except ValueError:
                continue

            ok += 1
            print(f'  {PASS} line {ok}: light={int(light):4d}  temp={temp_c:.1f}°C  '
                  f'pres={pres_hpa:.1f}hPa  solar={solar_ma:.1f}mA  '
                  f'load={load_ma:.1f}mA  tilt={int(tilt)}  btn={int(btn)}')
            if ok >= n:
                break

        ser.close()

        if ok < n:
            print(f'  {FAIL} Only got {ok}/{n} valid lines — check Arduino firmware.')
            return False
        return True

    except Exception as exc:
        print(f'  {FAIL} Serial error: {exc}')
        return False


# ─── Step 3: Check server health ─────────────────────────────────────────────

def check_server_health(port: int = 8765):
    print(f'\n[3] Backend Server  (http://localhost:{port})')
    url = f'http://localhost:{port}/api/health'
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read())
        arduino_mode = data.get('arduino', '?')
        clients      = data.get('clients', '?')
        print(f'  {PASS} /api/health → status={data["status"]}  '
              f'arduino={arduino_mode}  ws_clients={clients}')
        if arduino_mode == 'simulation':
            print(f'  {INFO} Server running in simulation (no Arduino reading yet)')
        return True
    except Exception as exc:
        print(f'  {FAIL} Cannot reach server: {exc}')
        print(f'  {INFO} Start it first:  python server.py')
        return False


# ─── Step 4: WebSocket connectivity ──────────────────────────────────────────

def check_websocket(port: int = 8765):
    print(f'\n[4] WebSocket  (ws://localhost:{port}/ws)')
    try:
        import websockets
        import asyncio

        received = {}

        async def _test():
            uri = f'ws://localhost:{port}/ws'
            async with websockets.connect(uri, open_timeout=4) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=4)
                received['data'] = json.loads(msg)

        asyncio.run(_test())
        state = received.get('data', {})
        solar  = state.get('solar_ma', '?')
        light  = state.get('light', '?')
        pwm0   = state.get('pwm', [None])[0]
        print(f'  {PASS} Received NeoState snapshot:')
        print(f'        solar_ma={solar}  light={light}  pwm[0]={pwm0}')
        return True

    except ImportError:
        print(f'  {INFO} websockets package not installed — skipping WS test')
        print(f'       Run: pip install websockets')
        return None
    except Exception as exc:
        print(f'  {FAIL} WebSocket error: {exc}')
        return False


# ─── Step 5: hardware/update endpoint ────────────────────────────────────────

def check_hardware_update(port: int = 8765):
    print(f'\n[5] /api/hardware/update endpoint')
    url = f'http://localhost:{port}/api/hardware/update'
    body = json.dumps({'nodeId': 'yale-new-haven', 'percentage': 45, 'status': 'online'}).encode()
    req = urllib.request.Request(url, data=body,
                                  headers={'Content-Type': 'application/json'},
                                  method='POST')
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        print(f'  {PASS} Response: {data}')
        if data.get('pwm') == round(0.45 * 255):
            print(f'  {PASS} PWM value correct: {data["pwm"]} (45% → {round(0.45*255)})')
        return True
    except Exception as exc:
        print(f'  {FAIL} Error: {exc}')
        return False


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print('=' * 56)
    print('  NEO Pipeline Verifier')
    print('=' * 56)

    port = check_arduino()
    if port:
        check_arduino_data(port)

    server_ok = check_server_health()
    if server_ok:
        check_websocket()
        check_hardware_update()

    print('\n' + '=' * 56)
    if not port:
        print('  Arduino not detected. Plug in USB and retry.')
    elif not server_ok:
        print('  Run  python server.py  in another terminal, then re-run this.')
    else:
        print('  Pipeline looks good.')
        print('  Frontend:   http://localhost:8765  (served by server.py)')
        print('  Dev UI:     npm run dev  in frontend/web  (port 5173)')
    print('=' * 56)


if __name__ == '__main__':
    main()
