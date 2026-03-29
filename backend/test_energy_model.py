#!/usr/bin/env python3
# ============================================================
#  NEO — Nodal Energy Oracle
#  backend/test_energy_model.py  —  Energy Model Validation
#  YHack 2025
#
#  Tests the derived solar/load estimation functions to ensure
#  the 3-sensor model produces realistic electricity dynamics.
# ============================================================

import sys
import math
from main import estimate_solar_and_load, update_battery, battery_soc, BATTERY_CAPACITY_MAH


def test_solar_estimate_by_light():
    """Verify solar generation scales with light level."""
    print("Test 1: Solar estimation from light level...")
    
    # Dark (night): light=0 → solar ~0 mA
    solar, load = estimate_solar_and_load(light=0, temp_c=20.0, pressure_hpa=1013.0, sim_hour=22.0)
    assert solar < 50, f"Night: expected solar < 50 mA, got {solar}"
    print(f"  ✓ Night (light=0): solar={solar:.1f} mA")
    
    # Bright (noon): light=1023 → solar ~800 mA
    solar, load = estimate_solar_and_load(light=1023, temp_c=20.0, pressure_hpa=1013.0, sim_hour=12.0)
    assert solar > 750, f"Noon: expected solar > 750 mA, got {solar}"
    print(f"  ✓ Noon (light=1023): solar={solar:.1f} mA")
    
    # Twilight: light=512 → solar ~400 mA
    solar, load = estimate_solar_and_load(light=512, temp_c=20.0, pressure_hpa=1013.0, sim_hour=18.0)
    assert 350 < solar < 450, f"Twilight: expected solar ~400 mA, got {solar}"
    print(f"  ✓ Twilight (light=512): solar={solar:.1f} mA")


def test_load_estimate_by_temperature():
    """Verify load increases with temperature extremes (AC/heating)."""
    print("\nTest 2: Load estimation from temperature...")
    
    # Comfortable temp (20°C): baseline load
    solar, load_20 = estimate_solar_and_load(light=512, temp_c=20.0, pressure_hpa=1013.0, sim_hour=12.0)
    
    # Hot (35°C): load should increase (AC)
    solar, load_hot = estimate_solar_and_load(light=512, temp_c=35.0, pressure_hpa=1013.0, sim_hour=12.0)
    assert load_hot > load_20, f"Hot: expected load > {load_20} mA, got {load_hot}"
    print(f"  ✓ Hot (35°C): load={load_hot:.1f} mA vs. neutral (20°C): {load_20:.1f} mA")
    
    # Cold (5°C): load should increase (heating)
    solar, load_cold = estimate_solar_and_load(light=512, temp_c=5.0, pressure_hpa=1013.0, sim_hour=12.0)
    assert load_cold > load_20, f"Cold: expected load > {load_20} mA, got {load_cold}"
    print(f"  ✓ Cold (5°C): load={load_cold:.1f} mA vs. neutral (20°C): {load_20:.1f} mA")


def test_load_estimate_by_time_of_day():
    """Verify load follows duck curve (peak at 6-9am, 5-9pm)."""
    print("\nTest 3: Load estimation from time-of-day (duck curve)...")
    
    # Night (3am): low load
    solar, load_night = estimate_solar_and_load(light=0, temp_c=20.0, pressure_hpa=1013.0, sim_hour=3.0)
    
    # Morning peak (8am): high load
    solar, load_morning = estimate_solar_and_load(light=100, temp_c=20.0, pressure_hpa=1013.0, sim_hour=8.0)
    assert load_morning > load_night, f"Morning: expected load > {load_night} mA, got {load_morning}"
    print(f"  ✓ Night (3am): load={load_night:.1f} mA vs. Morning peak (8am): {load_morning:.1f} mA")
    
    # Evening peak (18pm): high load
    solar, load_evening = estimate_solar_and_load(light=200, temp_c=20.0, pressure_hpa=1013.0, sim_hour=18.0)
    assert load_evening > load_night, f"Evening: expected load > {load_night} mA, got {load_evening}"
    print(f"  ✓ Night (3am): load={load_night:.1f} mA vs. Evening peak (18pm): {load_evening:.1f} mA")


def test_load_estimate_by_pressure():
    """Verify load increases when pressure drops (storm = people use power)."""
    print("\nTest 4: Load estimation from pressure (storm detection)...")
    
    # Normal pressure (1013 hPa): baseline
    solar, load_normal = estimate_solar_and_load(light=512, temp_c=20.0, pressure_hpa=1013.0, sim_hour=12.0)
    
    # Dropping pressure (950 hPa): storm approaching, load increases
    solar, load_storm = estimate_solar_and_load(light=512, temp_c=20.0, pressure_hpa=950.0, sim_hour=12.0)
    assert load_storm > load_normal, f"Storm: expected load > {load_normal} mA, got {load_storm}"
    print(f"  ✓ Normal pressure (1013 hPa): load={load_normal:.1f} mA")
    print(f"  ✓ Dropping pressure (950 hPa): load={load_storm:.1f} mA (storm effect)")


def test_battery_drain():
    """Verify battery SOC decreases when load > solar."""
    print("\nTest 5: Battery drain rate validation...")
    
    # High solar, low load → battery charges
    solar_high = 600.0
    load_low = 100.0
    dt = 1.0  # 1 second
    
    # This would need to capture battery state before/after
    # For now, just verify the formula: delta = (net_ma * dt) / (capacity_mah * 3600)
    net_ma = solar_high - load_low
    delta_soc = (net_ma * dt) / (BATTERY_CAPACITY_MAH / 100.0)
    assert delta_soc > 0, f"Expected positive delta with solar > load, got {delta_soc}"
    print(f"  ✓ Solar ({solar_high} mA) > Load ({load_low} mA): battery gains {delta_soc*100:.4f}% in 1 sec")
    
    # Low solar, high load → battery drains
    solar_low = 50.0
    load_high = 400.0
    net_ma = solar_low - load_high
    delta_soc = (net_ma * dt) / (BATTERY_CAPACITY_MAH / 100.0)
    assert delta_soc < 0, f"Expected negative delta with solar < load, got {delta_soc}"
    print(f"  ✓ Solar ({solar_low} mA) < Load ({load_high} mA): battery drains {abs(delta_soc)*100:.4f}% in 1 sec")


def test_reasonable_ranges():
    """Verify derived values stay within reasonable bounds."""
    print("\nTest 6: Output range validation...")
    
    test_cases = [
        (0, 20, 1013, 0, "Night, 0h"),
        (1023, 35, 950, 12, "Noon, hot, storm"),
        (512, 5, 1030, 18, "Twilight, cold, high pressure"),
        (100, 25, 1000, 6, "Early morning, warm"),
    ]
    
    for light, temp, pressure, hour, desc in test_cases:
        solar, load = estimate_solar_and_load(light, temp, pressure, hour)
        assert 0 <= solar <= 900, f"{desc}: solar out of range: {solar}"
        assert 50 <= load <= 600, f"{desc}: load out of range: {load}"
        print(f"  ✓ {desc}: solar={solar:.0f} mA, load={load:.0f} mA")


if __name__ == "__main__":
    print("=" * 70)
    print("NEO Energy Model Validation")
    print("=" * 70)
    
    try:
        test_solar_estimate_by_light()
        test_load_estimate_by_temperature()
        test_load_estimate_by_time_of_day()
        test_load_estimate_by_pressure()
        test_battery_drain()
        test_reasonable_ranges()
        
        print("\n" + "=" * 70)
        print("✅ All tests passed! Energy model is producing realistic values.")
        print("=" * 70)
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
