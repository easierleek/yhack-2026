#!/usr/bin/env python3
import sys
from flask import Flask, request, jsonify
from flask_cors import CORS
import json

app = Flask(__name__)
CORS(app)

def analyze_impact(directive_text, directive_lower):
    """Analyze the power impact of a directive"""
    
    # Determine overall impact direction
    if any(word in directive_lower for word in ['off', 'shutdown', 'emergency', 'reduce', 'save', 'cut', 'minimize', 'dim']):
        impact = "REDUCE"
        direction = "↓ Reducing power allocation"
        reason = "Directive aims to decrease power consumption"
    elif any(word in directive_lower for word in ['on', 'maximize', 'full', 'max', 'increase', 'boost', 'export', 'charge', 'priority']):
        impact = "INCREASE"
        direction = "↑ Increasing power allocation"
        reason = "Directive aims to increase power availability"
    else:
        impact = "BALANCED"
        direction = "≈ Maintaining balanced allocation"
        reason = "Directive requires adaptive balancing"
    
    return impact, direction, reason

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

@app.route('/api/mayor-directive', methods=['POST'])
def directive():
    data = request.get_json() or {}
    directive_text = data.get('directive', 'no directive')
    directive_lower = directive_text.lower()
    
    # Analyze power impact
    impact, direction, impact_reason = analyze_impact(directive_text, directive_lower)
    
    # Determine zone adjustments based on directive
    if 'off' in directive_lower or 'shutdown' in directive_lower or 'emergency' in directive_lower:
        zones = {
            "T1": {"brightness": 100, "change": "+10%", "reason": "Critical systems at full capacity for contingency"},
            "T2": {"brightness": 20, "change": "-60%", "reason": "Residential loads minimized"},
            "T3": {"brightness": 10, "change": "-90%", "reason": "Industrial operations suspended"},
            "T4": {"brightness": 0, "change": "-100%", "reason": "Commercial operations halted"}
        }
        battery_dir = "discharge"
        battery_rate = 50
    elif 'maximize' in directive_lower or 'full' in directive_lower or 'export' in directive_lower:
        zones = {
            "T1": {"brightness": 90, "change": "+5%", "reason": "Critical baseline maintained"},
            "T2": {"brightness": 90, "change": "+15%", "reason": "Residential load increased"},
            "T3": {"brightness": 85, "change": "+25%", "reason": "Industrial production ramped up"},
            "T4": {"brightness": 100, "change": "+50%", "reason": "Commercial export maximized"}
        }
        battery_dir = "discharge"
        battery_rate = 30
    elif 'save' in directive_lower or 'reduce' in directive_lower or 'cut' in directive_lower:
        zones = {
            "T1": {"brightness": 85, "change": "stable", "reason": "Critical protected at minimum safe level"},
            "T2": {"brightness": 50, "change": "-30%", "reason": "Residential demand curtailed"},
            "T3": {"brightness": 40, "change": "-50%", "reason": "Industrial operations throttled"},
            "T4": {"brightness": 30, "change": "-60%", "reason": "Commercial loads shed"}
        }
        battery_dir = "charge"
        battery_rate = 15
    elif 'solar' in directive_lower or 'battery' in directive_lower or 'charge' in directive_lower:
        zones = {
            "T1": {"brightness": 80, "change": "stable", "reason": "Critical baseline maintained"},
            "T2": {"brightness": 65, "change": "-10%", "reason": "Residential reduced to support storage"},
            "T3": {"brightness": 55, "change": "-5%", "reason": "Industrial minimally affected"},
            "T4": {"brightness": 100, "change": "+50%", "reason": "Export capacity maximized for revenue"}
        }
        battery_dir = "charge"
        battery_rate = 20
    else:
        # Default balanced response
        zones = {
            "T1": {"brightness": 90, "change": "stable", "reason": "Critical systems maintained at nom baseline"},
            "T2": {"brightness": 80, "change": "stable", "reason": "Residential at standard allocation"},
            "T3": {"brightness": 60, "change": "stable", "reason": "Industrial at efficient baseline"},
            "T4": {"brightness": 50, "change": "stable", "reason": "Commercial at balanced level"}
        }
        battery_dir = "stable"
        battery_rate = 0
    
    # Calculate overall power impact percentage
    total_current = 90 + 80 + 60 + 50  # baseline
    total_new = zones["T1"]["brightness"] + zones["T2"]["brightness"] + zones["T3"]["brightness"] + zones["T4"]["brightness"]
    power_change_pct = ((total_new - total_current) / total_current) * 100
    
    impact_statement = f"{direction} across all zones | {power_change_pct:+.0f}% total power allocation"
    
    return jsonify({
        "directive": directive_text,
        "interpretation": f"Received: {directive_text}",
        "strategy": impact,
        "response": f"🤖 NEO\n\n{impact_statement}\n\n{impact_reason}\n\nAdjusting power allocation across all grid zones...",
        "impact_analysis": {
            "overall_direction": direction,
            "power_change": f"{power_change_pct:+.1f}%",
            "reasoning": impact_reason
        },
        "zones": zones,
        "battery_impact": {"direction": battery_dir, "rate_percent": battery_rate},
        "solar_forecast": "Maintain" if battery_dir == "stable" else ("Store excess" if battery_dir == "charge" else "Maximize export"),
        "duration": "Until conditions change",
        "timestamp": "now"
    }), 200

if __name__ == '__main__':
    sys.stdout.flush()
    print("["+ "*"*60 + "]")
    print("[  NEO MAYOR CHAT API - CONTEXT-AWARE]")
    print("[  Port: 5000 - Ready for directives]")
    print("["+ "*"*60 + "]")
    sys.stdout.flush()
    app.run(host='0.0.0.0', port=5000, debug=False)
