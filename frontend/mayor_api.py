#!/usr/bin/env python3
# ============================================================
#  NEO — Nodal Energy Oracle
#  frontend/mayor_api.py  —  Mayor Directive REST API
#  YHack 2025
#
#  Provides Flask REST endpoints for the mayor directive chat interface.
# ============================================================

from flask import Flask, request, jsonify
import json

app = Flask(__name__)

# Import the mayor directive handler
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
from mayor_directive import parse_mayor_directive, format_response_for_chat


@app.route('/api/mayor-directive', methods=['POST'])
def handle_mayor_directive():
    """
    POST /api/mayor-directive
    
    Body: {
        "directive": "Heat emergency - cool the city",
        "current_state": {...NEO state object...}
    }
    
    Returns: {
        "response": "NEO's explanation of power adjustments",
        "strategy": {... tier adjustments ...}
    }
    """
    try:
        data = request.get_json()
        directive = data.get('directive', '').strip()
        current_state = data.get('current_state', {})
        
        if not directive:
            return jsonify({"error": "Empty directive"}), 400
        
        # Parse the directive
        analysis = parse_mayor_directive(directive, current_state)
        
        # Format response for chat
        response_text = format_response_for_chat(analysis)
        
        return jsonify({
            "response": response_text,
            "strategy": analysis['tier_adjustments'],
            "interpretation": analysis['interpretation'],
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    return jsonify({"status": "ok", "service": "neo-mayor-api"})


def start_mayor_api(host: str = "localhost", port: int = 5000, threaded: bool = True):
    """
    Start the mayor API server.
    
    Parameters
    ----------
    host : str
        Host to bind to (default: localhost)
    port : int
        Port to bind to (default: 5000)
    threaded : bool
        Whether to use threading (recommended for dev, set False in production with gunicorn)
    """
    print(f"[MAYOR-API] Starting on http://{host}:{port}")
    app.run(host=host, port=port, threaded=threaded, debug=False)


if __name__ == "__main__":
    start_mayor_api(host="0.0.0.0", port=5000)
