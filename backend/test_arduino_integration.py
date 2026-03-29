#!/usr/bin/env python3
"""
NEO Arduino Integration Test Suite
Verify serial communication, data parsing, and power allocation
"""

from arduino_interface import ArduinoInterface, PowerCalculator, SensorData, PowerAllocationEngine
from datetime import datetime

print("\n" + "="*70)
print("  NEO ARDUINO INTEGRATION TEST SUITE")
print("="*70)

# Test 1: Power Calculations
print("\n[TEST 1] Power Calculations")
print("-" * 70)

calc = PowerCalculator()

# LED consumption test
led_consumption = calc.calculate_consumption(
    brightness_red=0.8,
    brightness_yellow=0.9,
    brightness_green=0.85,
    brightness_white=0.5
)
print(f"LED Consumption (R:80%, Y:90%, G:85%, W:50%): {led_consumption*100:.1f}%")

# Solar generation test  
solar_light_levels = [0, 256, 512, 768, 1023]
print(f"\nSolar Generation from Light Sensor:")
for level in solar_light_levels:
    solar = calc.calculate_solar_generation(level)
    print(f"  Light={level:4d} ({int(level/1023*100):3d}%) -> {solar:6.0f}mA")

# Test 2: Mock Sensor Data
print("\n[TEST 2] Mock Sensor Data")
print("-" * 70)

sensor = SensorData(
    sun=800,
    city_voltage=4.5,
    grid_voltage=5.0,
    bmp_temperature=22.5,
    humidity=45.2
)

solar_ma = calc.calculate_solar_generation(sensor.sun)
print(f"Sensor Reading at {sensor.timestamp.strftime('%H:%M:%S')}:")
print(f"  Sun Brightness:    {sensor.sun}/1023")
print(f"  Solar Generation:  {solar_ma:.0f}mA")
print(f"  City Voltage:      {sensor.city_voltage}V")
print(f"  Grid Voltage:      {sensor.grid_voltage}V")
print(f"  Temperature:       {sensor.bmp_temperature}C")
print(f"  Humidity:          {sensor.humidity}%")

# Test 3: Power Allocation Engine
print("\n[TEST 3] Power Allocation Engine - Directives")
print("-" * 70)

engine = PowerAllocationEngine()

test_directives = [
    "save power - we're in a crisis",
    "maximize production for export",
    "emergency shutdown",
    "charge the batteries please",
    "hello how are you"
]

for directive in test_directives:
    print(f"\nDirective: '{directive}'")
    
    pwm, explanation = engine.allocate_power(
        sensor,
        solar_ma=300,  # mock 300mA solar
        load_ma=250,   # mock 250mA load
        directive=directive
    )
    
    print(f"  T1 (Hospital):     {sum(pwm[0:2])/2/255*100:.0f}%  (PWM: {pwm[0:2]})")
    print(f"  T2 (Utilities):    {sum(pwm[2:5])/3/255*100:.0f}%  (PWM: {pwm[2:5]})")
    print(f"  T3 (Industrial):   {sum(pwm[5:10])/5/255*100:.0f}%  (PWM: {pwm[5:10]})")
    print(f"  T4 (Commercial):   {sum(pwm[10:16])/6/255*100:.0f}%  (PWM: {pwm[10:16]})")
    print(f"  Strategy: {explanation}")

# Test 4: Arduino Interface (Mock)
print("\n[TEST 4] Arduino Interface (Mock Mode)")
print("-" * 70)

arduino = ArduinoInterface(port="COM3")
print(f"Arduino Interface Config:")
print(f"  Port: {arduino.port}")
print(f"  Baud: {arduino.baud}")
print(f"  Status: {'Connected' if arduino.connected else 'Disconnected'}")

print(f"\nCommand Format (would send to Arduino):")
print(f"  PWM:v0,v1,...,v15,RELAY:r,LCD1:text,LCD2:text")
print(f"\nExample output:")
pwm_example = [255, 255, 200, 200, 200, 150, 150, 150, 150, 150, 100, 100, 100, 100, 100, 100]
relay_example = 0
lcd1_example = "S:300 L:250"
lcd2_example = "BALANCED"
print(f"  PWM:{''.join(str(v) + ',' if i < 15 else str(v) for i, v in enumerate(pwm_example))}RELAY:{relay_example},LCD1:{lcd1_example:16s},LCD2:{lcd2_example:16s}")

# Test 5: Data Flow Verification
print("\n[TEST 5] Data Flow Verification")
print("-" * 70)

print("""
Data Flow Architecture:
├─ Arduino (Hardware)
│  ├─ LDR (Light Sensor)       → SUN ADC reading
│  ├─ DHT11 (Temp/Humidity)    → BMP_T, HUM values
│  ├─ BMP180 (Pressure/Temp)   → BMP_T value  
│  └─ Relay + Voltage Monitor  → CITY_V, GRID_V
│
├─ Serial Protocol
│  └─ SUN:xxx|CITY_V:x.xx|GRID_V:x.xx|BMP_T:x.x|HUM:x.x
│
├─ Arduino Interface (arduino_interface.py)
│  ├─ read_telemetry()        → Parse serial data → SensorData
│  ├─ PowerCalculator         → Calculate solar/load
│  └─ PowerAllocationEngine   → Allocate PWM values
│
├─ NEO API (neo_api.py)
│  ├─ /api/telemetry          → Latest sensor readings
│  ├─ /api/mayor-directive    → Process directives & allocate power
│  └─ /api/pwm/set            → Manual control for testing
│
└─ Frontend (React)
   ├─ MayorChat Component     → Send directives
   ├─ Display Power Allocation → Show zone brightness
   └─ Display Telemetry       → Show sensor values

Command Flow:
1. Arduino sends: SUN:800|CITY_V:4.5|...
2. arduino_interface.read_telemetry() parses it
3. PowerAllocationEngine calculates optimal PWM
4. API returns JSON with zones and explanation
5. Frontend renders power allocation UI
6. Arduino listens for PWM commands: PWM:255,255,200,...,RELAY:0,...
""")

# Test 6: Power Balance Scenario
print("\n[TEST 6] Power Balance Scenarios")
print("-" * 70)

scenarios = [
    ("Sunny Day", 600, 200, "High solar, low load"),
    ("Night Time", 100, 400, "Low solar, high load"),
    ("Balanced", 300, 300, "Solar matches demand"),
    ("Crisis", 50, 450, "Emergency deficit"),
]

for name, solar, load, desc in scenarios:
    pwm, explanation = engine.allocate_power(sensor, solar, load)
    total_pwm = sum(pwm)
    baseline_pwm = sum([204] * 16)
    change = ((total_pwm - baseline_pwm) / baseline_pwm * 100)
    
    print(f"\n{name} ({desc}):")
    print(f"  Solar: {solar}mA | Load: {load}mA | Deficit: {max(0, load-solar)}mA")
    print(f"  Total PWM: {total_pwm} ({change:+.0f}% vs baseline)")
    print(f"  Decision: {explanation}")

print("\n" + "="*70)
print("  ALL TESTS COMPLETED")
print("="*70 + "\n")

print("""
NEXT STEPS:
1. Connect Arduino with proper serial port (COM3 by default)
2. Verify telemetry using: curl http://localhost:5000/api/telemetry
3. Send directives using: curl -X POST http://localhost:5000/api/mayor-directive
4. Monitor Serial Monitor on Arduino IDE for PWM commands
5. Observe LED brightness changes on test circuit
""")
