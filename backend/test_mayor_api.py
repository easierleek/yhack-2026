#!/usr/bin/env python3
# ============================================================
#  NEO — Nodal Energy Oracle
#  test_mayor_api.py  —  Mayor API endpoint testing
#  YHack 2025
#
#  Quick validation that mayor directive API works end-to-end
# ============================================================

import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'frontend'))

from mayor_directive import parse_mayor_directive, format_response_for_chat
try:
    from mayor_api import app
except ImportError:
    from frontend.mayor_api import app

def test_api_endpoint():
    """Test the /api/mayor-directive endpoint"""
    print("Testing Mayor API endpoint...")
    
    # Create test client
    with app.test_client() as client:
        test_cases = [
            {
                "directive": "Heat emergency - cool the city",
                "expected_tier": "T2"
            },
            {
                "directive": "Industrial curfew after 10pm", 
                "expected_tier": "T2"
            },
            {
                "directive": "Rolling blackout warning",
                "expected_tier": "T4"
            },
            {
                "directive": "Solar subsidy event",
                "expected_tier": "T4"
            },
            {
                "directive": "Earthquake lockdown",
                "expected_tier": "T1"
            },
        ]
        
        for i, test in enumerate(test_cases, 1):
            response = client.post(
                '/api/mayor-directive',
                data=json.dumps({
                    'directive': test['directive'],
                    'current_state': {
                        'battery_soc': 0.5,
                        'temp_c': 25,
                        'light': 512,
                        'pressure_hpa': 1013,
                    }
                }),
                content_type='application/json'
            )
            
            print(f"\n[Test {i}] {test['directive']}")
            
            if response.status_code != 200:
                print(f"  ❌ FAILED: Status {response.status_code}")
                print(f"     {response.get_json()}")
                continue
            
            data = response.get_json()
            
            if not data.get('response'):
                print("  ❌ FAILED: Empty response")
                continue
            
            print(f"  ✅ Success")
            print(f"     Interpretation: {data['interpretation']}")
            print(f"     Response length: {len(data['response'])} chars")


def test_health_endpoint():
    """Test the /api/health endpoint"""
    print("\nTesting Mayor API health endpoint...")
    
    with app.test_client() as client:
        response = client.get('/api/health')
        
        if response.status_code != 200:
            print(f"  ❌ FAILED: Status {response.status_code}")
            return
        
        data = response.get_json()
        print(f"  ✅ Success")
        print(f"     Status: {data['status']}")
        print(f"     Service: {data['service']}")


if __name__ == "__main__":
    print("=" * 70)
    print("Mayor API Endpoint Testing")
    print("=" * 70)
    
    try:
        test_health_endpoint()
        test_api_endpoint()
        
        print("\n" + "=" * 70)
        print("✅ All tests passed! Mayor API is ready.")
        print("=" * 70)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
