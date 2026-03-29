# NEO Arduino Integration Guide

## Overview

This document describes the complete Arduino integration for the NEO Power Grid Optimization system, including hardware protocol, power calculations, and API architecture.

## Hardware Architecture

### Components
- **Arduino Microcontroller**: Main controller with:
  - LDR (Light Dependent Resistor) on A2 - measures solar generation
  - BMP180 Temperature/Pressure sensor on I2C
  - DHT11 Temperature/Humidity sensor on digital pin
  - Voltage monitoring on A1 (after relay) and A3 (bench supply)
  - Relay on digital pin 7 (switches between solar and grid)
  - PCA9685 PWM driver (16 channels at 400Hz for LED control)

### Communication Protocol

**Serial Connection**: 115200 baud, 8N1
**Format**: `SUN:xxx|CITY_V:x.xx|GRID_V:x.xx|BMP_T:x.x|HUM:x.x`
**Frequency**: 50ms interval (20Hz)

### Example Telemetry
```
SUN:800|CITY_V:4.5|GRID_V:5.0|BMP_T:22.5|HUM:45.2
SUN:750|CITY_V:4.6|GRID_V:5.0|BMP_T:22.6|HUM:45.1
```

## Power Calculations

### LED Power Consumption Formula
Based on LED current draw per color channel:
```
Total Consumption = 0.204*Red + 0.396*Yellow + 0.318*Green + 0.077*White
```
All values normalized 0-1 (0-100% brightness)

### Solar Generation (from LDR)
Linear conversion from ADC reading to current:
```
Solar_mA = (ADC_Reading / 1023) * 800mA
```
- ADC 0 = 0mA (complete darkness)
- ADC 512 = 400mA (50% light)
- ADC 1023 = 800mA (full sunlight)

### Power from Voltage Drop
Measures current via shunt resistor voltage drop:
```
Power_W = V² / R

Where:
  V = 5V - Measured_Voltage (voltage drop across shunt)
  R = 50Ω (shunt resistance)
```

## Grid Zone Hierarchy

### Zone Protection (T1 > T2 > T3 > T4)

**T1: Hospitals & Critical Services** (PWM Channels 0-1)
- Always protected to 100% brightness
- Penalty for reduction: -1000 per 1% cut
- Status: ALWAYS ON
- Brightness: 255 (100%)

**T2: Utilities** (PWM Channels 2-4)
- Secondary priority
- Penalty per 10% reduction: -50
- Normal: 80-100%
- Emergency reduce: 40%

**T3: Industrial** (PWM Channels 5-9)
- Moderate priority
- Penalty per 10% reduction: -20
- Normal: 70-90%
- Emergency reduce: 20%

**T4: Commercial/Revenue** (PWM Channels 10-15)
- Lowest priority
- Penalty per 10% reduction: -5
- Normal: 60-100%
- Emergency reduce: 0% (OFF)

## Power Allocation Modes

The `PowerAllocationEngine` supports three intelligent allocation strategies:

### 1. POWER DEFICIT MODE (Emergency)
**Triggered by**: "save power", "emergency", "reduce", "shutdown", "crisis"
```
T1 (Hospitals): 100% (255)
T2 (Utilities): 40% (102)
T3 (Industrial): 20% (51)
T4 (Commercial): 0% (0)
```
**When used**: Load exceeds solar generation significantly
**Impact**: Prioritizes essential services, shuts down commercial operations

### 2. POWER EXPORT MODE (Maximize)
**Triggered by**: "maximize", "export", "charge", "full", "boost"
```
T1 (Hospitals): 100% (255) [always]
T2 (Utilities): 90% (229)
T3 (Industrial): 90% (229)
T4 (Commercial): 100% (255)
```
**When used**: High solar generation, low load
**Impact**: Exports excess power to grid, charges battery, maximizes revenue

### 3. BALANCED MODE (Normal)
**Triggered by**: Other directives or mixed conditions
```
Adaptive based on solar/load ratio:
- Scale T2-T3 between 40% and 90% based on ratio
- Keep T4 between 30% and 100% based on ratio
- T1 always 100%
```
**When used**: Balanced generation and demand
**Impact**: Optimizes grid utilization while maintaining critical services

## Python Integration

### Module: `backend/arduino_interface.py`

**Key Classes**:

1. **SensorData** (dataclass)
   - `sun`: int (0-1023)
   - `city_voltage`: float
   - `grid_voltage`: float
   - `bmp_temperature`: float
   - `humidity`: float
   - `timestamp`: datetime (auto-generated)

2. **PowerCalculator**
   ```python
   calc = PowerCalculator()
   
   # LED consumption (0-1 brightness values)
   power_fraction = calc.calculate_consumption(0.8, 0.9, 0.85, 0.5)
   
   # Solar generation from LDR
   solar_ma = calc.calculate_solar_generation(800)  # returns ~627mA
   
   # Power from voltage drop
   power_w = calc.calculate_power_from_voltage(measured_voltage=4.5)
   ```

3. **ArduinoInterface**
   ```python
   arduino = ArduinoInterface(port="COM3")
   arduino.connect()
   
   # Read telemetry
   sensor_data = arduino.read_telemetry()
   
   # Send PWM commands
   pwm_values = [255, 255, 200, 200, 200, 150, 150, 150, 150, 150, 100, 100, 100, 100, 100, 100]
   arduino.send_command(pwm_values, relay=0, lcd1="Status", lcd2="Active")
   
   arduino.disconnect()
   ```

4. **PowerAllocationEngine**
   ```python
   engine = PowerAllocationEngine()
   
   # Get PWM allocation and explanation
   pwm_array, explanation = engine.allocate_power(
       sensor_data=sensor,
       solar_ma=300,
       load_ma=250,
       directive="save power"
   )
   
   # pwm_array: 16-element list (0-255 each)
   # explanation: str (e.g., "POWER DEFICIT MODE | Reducing...")
   ```

### Module: `backend/neo_api.py`

**Flask API Endpoints**:

**GET /api/health**
```json
{
  "status": "ok",
  "arduino": "connected|disconnected",
  "sensor_data": true
}
```

**GET /api/telemetry**
```json
{
  "sun": 800,
  "solar_ma": 627,
  "city_voltage": 4.5,
  "grid_voltage": 5.0,
  "temperature": 22.5,
  "humidity": 45.2,
  "current_pwm": [255, 255, 200, ...],
  "relay_state": "Grid",
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

**POST /api/mayor-directive**
```json
{
  "directive": "save power during crisis"
}
```

Response:
```json
{
  "strategy": "POWER DEFICIT MODE",
  "zones": {
    "T1_hospitals": {"brightness": 100, "pwm": [255, 255]},
    "T2_utilities": {"brightness": 40, "pwm": [102, 102, 102]},
    "T3_industrial": {"brightness": 20, "pwm": [51, 51, 51, 51, 51]},
    "T4_commercial": {"brightness": 0, "pwm": [0, 0, 0, 0, 0, 0]}
  },
  "impact_analysis": {
    "direction": "Reducing power allocation",
    "power_change_percent": -45,
    "explanation": "Load (500mA) exceeds solar generation (100mA) - activating emergency mode"
  },
  "telemetry": {
    "solar_ma": 100,
    "load_ma": 500,
    "temperature": 22.5,
    "humidity": 45.2
  },
  "battery_impact": {
    "direction": "discharging",
    "rate_percent": 8
  },
  "solar_forecast": "Deficit",
  "response": "NEO Power Allocation\n\nSolar: 100mA vs Load: 500mA\n\nEMERGENCY MODE - Activating deficit reduction...\nHospitals: 100% | Utilities: 40% | Industrial: 20% | Commercial: OFF\n\nBattery Status: Discharging at 8%/min"
}
```

**POST /api/pwm/set**
```json
{
  "pwm": [255, 255, 200, 200, 200, 150, 150, 150, 150, 150, 100, 100, 100, 100, 100, 100],
  "relay": 0,
  "lcd1": "Custom Test",
  "lcd2": "Manual Mode"
}
```

## Testing

### Run Integration Tests
```bash
cd backend
python test_arduino_integration.py
```

### Test Output
```
=== ARDUINO INTEGRATION TEST ===

1. LED Power Consumption Formula:
   Input: R=80%, Y=90%, G=85%, W=50%
   Result: 82.8%
   Expected: 82.8%
   PASS: True

2. Solar Generation (LDR 0-1023 to 0-800mA):
   ADC    0 (100%=0%) -> 0mA OK
   ADC 1023 (100%=800%) -> 800mA OK
   PASS: True

3. Power Allocation Zones:
   Scenario: Emergency (save power)
   T1 (Hospitals): 100%
   T2 (Utilities): 40%
   T3 (Industrial): 20%
   T4 (Commercial): 0%
   PASS: True
```

## Deployment Checklist

- [ ] Arduino connected to COM3 (or configured port)
- [ ] Serial communication verified (tools like Arduino IDE Serial Monitor)
- [ ] Backend dependencies installed: `pip install -r requirements.txt`
- [ ] Neo API running: `python backend/neo_api.py`
- [ ] Telemetry thread active (check API health endpoint)
- [ ] Frontend connected to `http://localhost:5000/api/mayor-directive`
- [ ] Power allocation responds to directives
- [ ] LED brightness changes match zone allocations
- [ ] Battery charging/discharging calculations correct

## Arduino Code Reference

### Serial Read Example
```cpp
// Arduino receives directives
if (Serial.available()) {
  String cmd = Serial.readStringUntil('\n');
  // Parse: PWM:v0,v1,...,v15,RELAY:r,LCD1:text,LCD2:text
}

// Arduino sends telemetry
void sendTelemetry() {
  int sun = analogRead(A2);
  float city_v = analogRead(A1) * 5.0/1023;
  float grid_v = analogRead(A3) * 5.0/1023;
  float temp = readBMP180Temperature();
  float humidity = readDHT11Humidity();
  
  Serial.print("SUN:");
  Serial.print(sun);
  Serial.print("|CITY_V:");
  Serial.print(city_v);
  Serial.print("|GRID_V:");
  Serial.print(grid_v);
  Serial.print("|BMP_T:");
  Serial.print(temp);
  Serial.print("|HUM:");
  Serial.println(humidity);
}
```

## Data Flow Diagram

```
Hardware Layer:
├─ Arduino Microcontroller
│  ├─ LDR (A2) ─────────────────┐
│  ├─ BMP180 (I2C) ──────────────┤
│  ├─ DHT11 (Digital) ───────────┤
│  ├─ Voltage Sensors (A1,A3) ───┤
│  └─ Relay (Digital 7) ─────────┤
│                                 │
│  Serial Output (115200 baud)    │ Parse
│  "SUN:800|CITY_V:4.5|..."      │
│                                 │
Serial Protocol Layer:            │
│────────────────────────────────┘
│
Application Layer:
├─ arduino_interface.py
│  ├─ ArduinoInterface.read_telemetry()
│  │  └─ SensorData(sun=800, city_voltage=4.5, ...)
│  │
│  ├─ PowerCalculator
│  │  ├─ calculate_solar_generation(800) → 627mA
│  │  ├─ calculate_consumption(...) → power_fraction
│  │  └─ calculate_power_from_voltage(...) → watts
│  │
│  └─ PowerAllocationEngine.allocate_power()
│     ├─ Parse directive (save/maximize/normal)
│     ├─ Calculate PWM values (0-255 × 16 channels)
│     └─ Generate explanation string
│
├─ neo_api.py (Flask)
│  ├─ Background telemetry thread (20Hz)
│  ├─ POST /api/mayor-directive
│  │  ├─ Receive user directive
│  │  ├─ Call PowerAllocationEngine
│  │  ├─ Send command to Arduino
│  │  └─ Return JSON response with zones + explanation
│  │
│  ├─ GET /api/telemetry
│  │  └─ Return current sensor data
│  │
│  └─ GET /api/health
│     └─ Return connection status
│
Frontend Layer:
└─ React MayorChat Component
   ├─ Send directives
   ├─ Display zone brightness (T1-T4)
   ├─ Show solar forecast
   ├─ Display battery impact
   └─ Show chatbot explanation
```

## Troubleshooting

### Arduino Not Connecting
- Check COM port: `python -m serial.list_ports`
- Verify 115200 baud rate
- Try restarting Arduino IDE Serial Monitor, then API

### No Telemetry Data
- Verify sensors are connected and functional
- Check Arduino serial output in IDE Serial Monitor
- Confirm `telemetry_thread` is running (check API logs)

### PWM Not Changing
- Verify PCA9685 I2C address (default 0x40)
- Check Arduino code for command parsing
- Test manual PWM via `/api/pwm/set` endpoint

### Incorrect Power Calculations
- Verify ADC reference voltage (should be 5V)
- Check shunt resistor value (50Ω)
- Confirm LED current coefficients match circuit

## Files

- `backend/arduino_interface.py` - Hardware abstraction layer (378 lines)
- `backend/neo_api.py` - Flask API with telemetry integration (260 lines)
- `backend/test_arduino_integration.py` - Integration tests and verification
- `hardware/neo_arduino/neo_arduino.ino` - Arduino firmware
- This file: `ARDUINO_INTEGRATION.md` - Complete documentation

## Next Steps

1. Connect Arduino hardware
2. Verify serial communication
3. Run integration tests: `python backend/test_arduino_integration.py`
4. Start API: `python backend/neo_api.py`
5. Test endpoints with curl or frontend
6. Monitor LED brightness changes and battery calculations
7. Deploy to production dashboard
