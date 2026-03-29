#!/usr/bin/env python3
"""
NEO Mayor Chat API with Arduino Integration
Real-time power management with AI decision-making
"""

import sys
import json
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from arduino_interface import ArduinoInterface, PowerCalculator, PowerAllocationEngine, SensorData
from k2_client import K2Client
import threading
import time
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# Initialize K2 client for intelligent responses
k2_api_key = os.getenv('K2_API_KEY', '')
k2_client = None
if k2_api_key:
    try:
        k2_client = K2Client(api_key=k2_api_key)
        print("[K2] Initialized AI response engine")
    except Exception as e:
        print(f"[K2] Failed to initialize: {e}")
else:
    print("[K2] No API key - using basic responses")

# Global state
arduino = ArduinoInterface(port="COM3", baud=115200)
power_calc = PowerCalculator()
power_engine = PowerAllocationEngine()

current_sensor_data = None
current_pwm = [204] * 16
current_relay = 0
last_telemetry_time = 0

def telemetry_loop():
    """Background thread: continuously read Arduino telemetry"""
    global current_sensor_data, last_telemetry_time
    
    print("[TELEMETRY] Starting background sensor read loop...")
    
    while True:
        try:
            if arduino.connected:
                sensor = arduino.read_telemetry()
                if sensor:
                    current_sensor_data = sensor
                    last_telemetry_time = time.time()
            
            time.sleep(0.05)  # 20Hz reading
        
        except Exception as e:
            print(f"[TELEMETRY] Error: {e}")
            time.sleep(0.1)

def start_telemetry_thread():
    """Start background telemetry thread"""
    thread = threading.Thread(target=telemetry_loop, daemon=True)
    thread.start()
    print("[TELEMETRY] Background thread started")

def calculate_power_impact(directive: str) -> dict:
    """Calculate power allocation change from directive"""
    
    directive_lower = directive.lower()
    
    if any(word in directive_lower for word in ['off', 'shutdown', 'emergency', 'reduce', 'save', 'cut', 'minimize', 'dim']):
        strategy = "REDUCE"
        direction = "Reducing power allocation"
    elif any(word in directive_lower for word in ['on', 'maximize', 'full', 'max', 'increase', 'boost', 'export', 'charge', 'priority']):
        strategy = "INCREASE"
        direction = "Increasing power allocation"
    else:
        strategy = "BALANCED"
        direction = "Maintaining balanced allocation"
    
    return {
        "strategy": strategy,
        "direction": direction
    }

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "arduino": "connected" if arduino.connected else "disconnected",
        "sensor_data": current_sensor_data is not None
    }), 200

@app.route('/api/telemetry', methods=['GET'])
def get_telemetry():
    """Get latest sensor readings from Arduino"""
    if not current_sensor_data:
        return jsonify({"error": "No sensor data available"}), 503
    
    return jsonify({
        "timestamp": current_sensor_data.timestamp.isoformat(),
        "sun": current_sensor_data.sun,
        "city_voltage": current_sensor_data.city_voltage,
        "grid_voltage": current_sensor_data.grid_voltage,
        "temperature": current_sensor_data.bmp_temperature,
        "humidity": current_sensor_data.humidity,
        "solar_ma": power_calc.calculate_solar_generation(current_sensor_data.sun),
        "pwm": current_pwm,
        "relay": current_relay
    }), 200

@app.route('/api/mayor-directive', methods=['POST'])
def mayor_directive():
    """
    Process mayor directive and allocate power with AI reasoning
    """
    data = request.get_json() or {}
    directive_text = data.get('directive', 'no directive')
    
    if not current_sensor_data:
        return jsonify({"error": "No sensor data - Arduino not connected"}), 503
    
    # Calculate solar and load
    solar_ma = power_calc.calculate_solar_generation(current_sensor_data.sun)
    
    # Estimate load from city voltage
    city_load_current = max(0, 22.0 - current_sensor_data.city_voltage) * 100
    load_ma = city_load_current
    
    # Get power allocation from engine
    pwm, explanation = power_engine.allocate_power(
        current_sensor_data,
        solar_ma,
        load_ma,
        directive_text
    )
    
    # Calculate power impact
    impact = calculate_power_impact(directive_text)
    
    # Calculate total power change
    total_current = sum([204] * 16)  # baseline 80%
    total_new = sum(pwm) 
    power_change_pct = ((total_new - total_current) / total_current) * 100
    
    # Build zones response
    zones = {
        "T1": {
            "name": "Hospitals",
            "brightness": f"{(pwm[0] / 255 * 100):.0f}%",
            "channels": pwm[0:2]
        },
        "T2": {
            "name": "Utilities", 
            "brightness": f"{(sum(pwm[2:5]) / 3 / 255 * 100):.0f}%",
            "channels": pwm[2:5]
        },
        "T3": {
            "name": "Industrial",
            "brightness": f"{(sum(pwm[5:10]) / 5 / 255 * 100):.0f}%",
            "channels": pwm[5:10]
        },
        "T4": {
            "name": "Commercial",
            "brightness": f"{(sum(pwm[10:16]) / 6 / 255 * 100):.0f}%",
            "channels": pwm[10:16]
        }
    }
    
    # Send command to Arduino
    relay = 1 if solar_ma < load_ma * 1.2 else 0
    lcd_line1 = f"S:{solar_ma:.0f}mA L:{load_ma:.0f}mA"
    lcd_line2 = f"{impact['strategy'][:8]}"
    
    arduino.send_command(pwm, relay, lcd_line1, lcd_line2)
    
    # Update global state
    global current_pwm, current_relay
    current_pwm = pwm
    current_relay = relay
    
    # Generate intelligent response using K2
    neo_response = generate_ai_response(
        directive_text,
        solar_ma,
        load_ma,
        pwm,
        zones,
        explanation
    )
    
    # Build response
    response = {
        "directive": directive_text,
        "strategy": impact['strategy'],
        "interpretation": f"Received: {directive_text}",
        "response": neo_response,
        "impact_analysis": {
            "overall_direction": impact['direction'],
            "power_change": f"{power_change_pct:+.1f}%",
            "reasoning": explanation
        },
        "zones": zones,
        "telemetry": {
            "solar_ma": f"{solar_ma:.0f}",
            "load_ma": f"{load_ma:.0f}",
            "temperature": f"{current_sensor_data.bmp_temperature:.1f}C",
            "humidity": f"{current_sensor_data.humidity:.1f}%"
        },
        "battery_impact": {
            "direction": "charge" if solar_ma > load_ma else "discharge",
            "rate_percent": int((abs(solar_ma - load_ma) / max(solar_ma, load_ma)) * 100) if max(solar_ma, load_ma) > 0 else 0
        },
        "solar_forecast": "Maximize export" if solar_ma > load_ma * 1.5 else ("Maintain balance" if solar_ma > load_ma else "Deficit - reduce load"),
        "relay_state": "Grid" if relay else "Solar"
    }
    
    return jsonify(response), 200

def generate_ai_response(directive_text: str, solar_ma: float, load_ma: float, pwm: list, zones: dict, explanation: str) -> str:
    """Generate intelligent response using K2 LLM or fallback"""
    
    if not k2_client:
        # Fallback: simple response
        return f"NEO Power Allocation\n\n{explanation}\n\nDirective: {directive_text}"
    
    system_prompt = """You are NEO (Nodal Energy Oracle), an AI power management system for a smart city.
    
Your role:
- Respond to mayor directives about power allocation
- Explain power allocation decisions in natural, human-friendly language
- Balance critical services (hospitals) with revenue (commercial zones)
- Reference actual sensor data and grid conditions
- Be concise but informative

Power Grid Zones:
- T1 (Hospitals): Always protected, essential services - PRIORITY
- T2 (Utilities): Secondary infrastructure - HIGH PRIORITY
- T3 (Industrial): Manufacturing and processing - MODERATE PRIORITY
- T4 (Commercial): Retail and general business - LOWER PRIORITY, revenue generator

Your response should:
1. Acknowledge the directive
2. Explain the power allocation decision
3. Reference actual solar generation and load
4. Show which zones are affected
5. Be 2-3 sentences, natural and conversational"""

    user_context = {
        "directive": directive_text,
        "solar_generation_ma": solar_ma,
        "current_load_ma": load_ma,
        "power_allocation": {
            "T1_hospitals": f"{(pwm[0] / 255 * 100):.0f}%",
            "T2_utilities": f"{(sum(pwm[2:5]) / 3 / 255 * 100):.0f}%",
            "T3_industrial": f"{(sum(pwm[5:10]) / 5 / 255 * 100):.0f}%",
            "T4_commercial": f"{(sum(pwm[10:16]) / 6 / 255 * 100):.0f}%"
        },
        "technical_reasoning": explanation,
        "power_deficit_mode": solar_ma < load_ma,
        "power_export_mode": solar_ma > load_ma * 1.5
    }
    
    try:
        k2_response = k2_client.call(system_prompt, user_context)
        if k2_response.success or k2_response.cached:
            # Extract text response
            response_text = k2_response.raw_response
            if hasattr(k2_response, 'raw_response') and k2_response.raw_response:
                response_text = k2_response.raw_response
            else:
                response_text = explanation
            
            return f"NEO: {response_text}"
        else:
            # K2 failed but we have cache or error message
            return f"NEO Power Allocation\n\n{explanation}\n\n[Using fallback mode]"
    except Exception as e:
        print(f"[K2] Error generating response: {e}")
        # Fallback to technical explanation
        return f"NEO Power Allocation\n\n{explanation}"

@app.route('/api/pwm/set', methods=['POST'])
def set_pwm():
    """Manually set PWM values for testing"""
    data = request.get_json() or {}
    pwm_values = data.get('pwm', [204] * 16)
    relay = data.get('relay', 0)
    
    if len(pwm_values) != 16:
        return jsonify({"error": "PWM array must have 16 values"}), 400
    
    global current_pwm, current_relay
    current_pwm = pwm_values
    current_relay = relay
    
    if arduino.connected:
        arduino.send_command(pwm_values, relay, "Manual PWM", "Test")
    
    return jsonify({"status": "ok", "pwm": pwm_values, "relay": relay}), 200

if __name__ == '__main__':
    print("\n" + "="*60)
    print("  NEO MAYOR CHAT API - ARDUINO INTEGRATED")
    print("  Smart City Power Management")
    print("="*60 + "\n")
    
    # Connect to Arduino
    if arduino.connect():
        print("[STATUS] Arduino CONNECTED\n")
        start_telemetry_thread()
    else:
        print("[STATUS] Running without Arduino (mock mode)\n")
    
    print(f"API Endpoints:")
    print(f"  GET  /api/health")
    print(f"  GET  /api/telemetry")
    print(f"  POST /api/mayor-directive")
    print(f"  POST /api/pwm/set")
    print(f"\nStarting server on port 5000...\n")
    
    sys.stdout.flush()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
