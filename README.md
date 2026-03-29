# ⚡ NEO — Nodal Energy Oracle

**AI-Powered Smart City Power Grid Management**

NEO intelligently optimizes energy distribution across city zones (hospitals → utilities → industrial → commercial) using real-time hardware sensors and K2 Think V2 LLM. City officials interact with an AI chatbot that explains power allocation decisions and adjusts zones based on renewable energy availability, load demand, and service priorities.

---

## 🎯 Quick Start

### 1️⃣ Local Development (Backend + Frontend)

```bash
# Clone & setup
git clone https://github.com/easierleek/yhack-2026.git
cd "Yale Hack"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
npm install --prefix frontend/web

# Start backend (port 5000)
python backend/neo_api.py

# In another terminal: Start frontend (port 5175)
cd frontend/web
npm run dev
```

Visit **http://localhost:5175** to test locally.

### 2️⃣ Production Deployment

**Frontend:** GoDaddy (already deployed)  
**Backend:** Railway at `https://neo-power-production.up.railway.app`

The frontend calls the Railway backend API at `/api/mayor-directive`.

---

## 📊 System Architecture

```
┌─────────────────────────────────────────┐
│   Frontend (React + Vite + Leaflet)    │
│   GoDaddy / localhost:5175              │
└────────────────┬────────────────────────┘
                 │ HTTP POST
                 ↓
┌─────────────────────────────────────────┐
│   Backend API (Flask + Python)          │
│   Railway / localhost:5000               │
│   - K2 LLM Integration                  │
│   - Power Allocation Engine             │
│   - Arduino Serial Interface            │
└────────────────┬────────────────────────┘
                 │ Serial (COM3)
                 ↓
┌─────────────────────────────────────────┐
│   Hardware (Arduino + Sensors)          │
│   - LDR (solar generation)              │
│   - BMP180 (temperature)                │
│   - DHT11 (humidity)                    │
│   - PCA9685 (16-ch PWM for LEDs)       │
│   - Relay (city/grid switching)         │
└─────────────────────────────────────────┘
```

---

## 🔌 Hardware Setup

**Arduino**: Arduino Uno with sensors and power management

**Telemetry Format** (115200 baud, 50ms interval):
```
SUN:xxx|CITY_V:x.xx|GRID_V:x.xx|BMP_T:x.x|HUM:x.x
```

**Control Format** (from backend to Arduino):
```
PWM:v0,v1,...,v15,RELAY:r,LCD1:text,LCD2:text
```

**Sensor Mappings:**
- `SUN`: 0-1023 ADC → 0-800mA solar generation
- `CITY_V`: Voltage after relay (0-5V)
- `GRID_V`: Grid potential before relay (0-5V)
- `BMP_T`: Temperature in °C
- `HUM`: Humidity %

---

## 🎮 API Endpoints

### `POST /api/mayor-directive`

Send a directive to the grid operator.

**Request:**
```json
{
  "directive": "save power",
  "current_state": {
    "zones": {"T1": 80, "T2": 60, "T3": 40, "T4": 20}
  }
}
```

**Response:**
```json
{
  "response": "NEO: Reducing commercial zones by 15% while protecting hospitals at 100%. Current solar: 450mA...",
  "pwm": [204, 204, ..., 51],
  "relay": 0,
  "impact": {
    "direction": "REDUCE",
    "zones_affected": ["T4", "T3"],
    "explanation": "..."
  }
}
```

### `GET /api/health`

Check backend status.

**Response:**
```json
{
  "status": "ok",
  "arduino_connected": false,
  "k2_initialized": true
}
```

### `GET /api/telemetry`

Get latest sensor readings.

**Response:**
```json
{
  "sun": 512,
  "city_voltage": 4.2,
  "grid_voltage": 4.8,
  "bmp_temperature": 22.5,
  "humidity": 55.0,
  "timestamp": "2026-03-29T14:30:00Z"
}
```

---

## ⚙️ Configuration

Create a `.env` file in the root directory:

```bash
# K2 LLM API
K2_API_KEY=your_k2_think_v2_api_key

# Arduino
ARDUINO_PORT=COM3  # Windows: COM3, Linux: /dev/ttyUSB0
ARDUINO_BAUD=115200

# (Optional) GoDaddy domain for CORS
ALLOWED_ORIGINS=https://your-domain.com
```

---

## 🚀 Deployment

### Railway Backend

1. Push to GitHub main: `git push origin main`
2. Railway auto-deploys via GitHub webhook
3. Procfile specifies entry point: `web: cd backend && python neo_api.py`
4. Set `K2_API_KEY` in Railway environment variables

### Frontend (GoDaddy)

Already deployed. The frontend calls the Railway API backend.

To update frontend:
```bash
cd frontend/web
npm run build
# Copy dist/ contents to GoDaddy hosting
```

---

## 🧠 Power Allocation Algorithm

NEO protects critical services while maximizing renewable energy use:

**Zone Hierarchy** (16 PWM channels):
- **T1 (Hospitals)**: Channels 0-1, min 90% power
- **T2 (Utilities)**: Channels 2-4, min 70% power
- **T3 (Industrial)**: Channels 5-9, min 50% power
- **T4 (Commercial)**: Channels 10-15, flexible

**K2 LLM Integration:**

When users send directives ("save power", "maximize production", etc.), the backend:

1. Calculates current solar generation from LDR
2. Estimates load from voltage measurements
3. Determines power deficit/surplus mode
4. Passes context to K2 to generate intelligent response
5. Returns power allocation changes + AI explanation

Circuit breaker pattern: if K2 fails, system falls back to technical explanations.

---

## 🛠️ Development

### Backend

```bash
# Run with mock Arduino (no hardware needed)
python backend/neo_api.py

# Tests
python backend/test_logic.py
python backend/test_integration.py
```

### Frontend

```bash
cd frontend/web
npm run dev      # Dev server
npm run build    # Production build
npm run preview  # Preview build
```

### Arduino

1. Open `hardware/neo_arduino/neo_arduino.ino` in Arduino IDE
2. Select Board: Arduino Uno
3. Select Port: COM3 (or your port)
4. Upload

---

## 📝 Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `K2_API_KEY` | (required) | K2 Think V2 API key |
| `ARDUINO_PORT` | `COM3` | Serial port for Arduino |
| `ARDUINO_BAUD` | `115200` | Serial baud rate |
| `ALLOWED_ORIGINS` | `*` | CORS origins for API |

---

## 🧪 Testing the Chat API

**Local:**
```bash
curl -X POST http://localhost:5000/api/mayor-directive \
  -H "Content-Type: application/json" \
  -d '{"directive":"save power", "current_state":{}}'
```

**On Railway:**
```bash
curl -X POST https://neo-power-production.up.railway.app/api/mayor-directive \
  -H "Content-Type: application/json" \
  -d '{"directive":"save power", "current_state":{}}'
```

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| **Chat not working on GoDaddy** | Frontend code calls Railway API. Check Network tab in DevTools for 200 response. |
| **"No Arduino connection" warning** | Expected if hardware not plugged in. System runs in mock mode. |
| **K2 responses are generic** | Either K2_API_KEY missing or circuit breaker triggered. Check backend logs. |
| **Frontend won't build** | Delete `node_modules`, run `npm install`, then `npm run build`. |

---

## 📚 Tech Stack

- **Backend**: Python, Flask, K2 Think V2 LLM
- **Frontend**: React, TypeScript, Vite, Leaflet
- **Hardware**: Arduino Uno, LDR, BMP180, DHT11, PCA9685
- **Deployment**: Railway (backend), GoDaddy (frontend)
- **Version Control**: Git/GitHub

---

## 📄 Project Structure

```
neo/
├── backend/
│   ├── neo_api.py              # Flask API + K2 LLM integration
│   ├── arduino_interface.py    # Serial communication & power calculations
│   ├── k2_client.py            # K2 API client with resilience
│   ├── requirements.txt        # Python dependencies
│   └── test_*.py               # Unit & integration tests
├── frontend/
│   └── web/
│       ├── src/
│       │   ├── components/MayorChat.tsx     # Chat UI
│       │   ├── components/CityMap.tsx       # Leaflet map
│       │   └── App.tsx                      # Main app
│       ├── package.json
│       └── vite.config.ts
├── hardware/
│   └── neo_arduino/
│       └── neo_arduino.ino     # Arduino firmware
├── Procfile                    # Railway deployment
├── README.md                   # This file
└── .env                        # Environment variables (local only)
│       └── neo_arduino.ino      # Arduino firmware (Jeffery)
│
├── backend/
│   ├── main.py                  # AI control loop — entry point (Turtle)
│   ├── eia_client.py            # EIA API market price module (Andrew)
│   └── requirements.txt
│
├── frontend/
│   └── dashboard.py             # Rich terminal dashboard (Andrew)
│
└── README.md
```

---

## Hardware Bill of Materials

| # | Component | Purpose |
|---|-----------|---------|
| 1 | Arduino Uno | Main microcontroller |
| 1 | MB102 Breadboard Power Supply | Green Grid (solar proxy) |
| 1 | 5V 5A DC Adapter | State Grid (utility) |
| 1 | PCA9685 16-Ch PWM Driver | Controls all 24 LEDs |
| 2 | INA219 DC Current Sensor | Measure solar mA and load mA |
| 1 | 5V Relay Module | Switch between Green / State grid |
| 1 | DHT11 Temp/Humidity Sensor | Temperature → T2 demand |
| 1 | BMP180 Pressure Sensor | Pressure trend → storm prediction |
| 1 | Photoresistor (LDR) | Solar proxy — light level |
| 2 | 10kΩ Potentiometers | Residential demand knobs |
| 1 | Tilt Switch | Seismic sensor → earthquake lockdown |
| 5 | Push Buttons | Mayor policy buttons |
| 1 | I2C LCD 16×2 | Status display |
| 2 | White LEDs | Tier 1 — Hospitals (CH 0–1) |
| 3 | Red LEDs | Tier 2 — Utilities (CH 2–4) |
| 5 | Green LEDs | Tier 3 — Residential (CH 5–9) |
| 6 | Yellow LEDs | Tier 4 — Commercial (CH 10–15) |
| — | 330Ω resistors × 16 | Current limiting for LEDs |
| 1 | 0.1µF capacitor | Decoupling on VCC rail |

---

## I2C Address Map

> ⚠️ The PCA9685 and INA219 both default to `0x40`. You MUST solder the
> address jumpers on the INA219 boards before wiring.

| Device | I2C Address | How to set |
|--------|-------------|------------|
| PCA9685 PWM Driver | `0x40` | Default — no change |
| INA219 Solar Sense | `0x41` | Bridge the **A0** pad on the INA219 board |
| INA219 Load Sense | `0x44` | Bridge the **A1** pad on the INA219 board |
| LCD 16×2 | `0x27` | Check back of your module (may be `0x3F`) |
| BMP180 | `0x77` | Fixed — no change |

---

## Arduino Pin Map

| Arduino Pin | Connected To |
|-------------|-------------|
| `A0` | LDR (photoresistor) voltage divider |
| `A1` | Potentiometer 1 wiper |
| `A2` | Potentiometer 2 wiper |
| `D2` | Tilt switch (active LOW, internal pullup) |
| `D3` | Mayor Button 1 — Industrial Curfew |
| `D4` | Mayor Button 2 — Solar Subsidy |
| `D5` | Mayor Button 3 — Brownout Protocol |
| `D6` | Mayor Button 4 — Emergency Grid |
| `D7` | Relay control signal |
| `D8` | Mayor Button 5 — Commercial Lockdown |
| `D9` | DHT11 data |
| `SDA (A4)` | I2C bus — PCA9685, INA219 ×2, LCD, BMP180 |
| `SCL (A5)` | I2C bus — PCA9685, INA219 ×2, LCD, BMP180 |

---

## Serial Protocol

The Arduino and Python communicate over USB at **9600 baud**.

### Arduino → Python (every 100 ms)
```
light,temp_c,pressure_hpa,solar_ma,load_ma,pot1,pot2,tilt,button\n
```
Example:
```
842,23.4,1013.2,312.5,287.1,512,480,0,0
```

### Python → Arduino (after each K2 decision)
```
PWM:v0,v1,...,v15,RELAY:r,LCD1:line1,LCD2:line2\n
```
Example:
```
PWM:255,255,255,255,255,204,204,204,204,204,128,128,128,128,128,128,RELAY:0,LCD1:SOC:72% $1.20,LCD2:Score:+4820
```

---

## Wiring: Dual-Grid Power Architecture

```
MB102 5V rail  ──────────────────────────────► INA219 Solar (0x41)
                                                         │
                                                    (solar_ma)
                                                         │
5V Adapter ──► Relay (NC) ─────────────────────────────►│
               Relay (NO) ─────► INA219 Load (0x44) ────►│
                                        │                │
                                   (load_ma)             │
                                        │                │
                                        └────────────────┘
                                                 │
                                      PCA9685 V+ rail
                                         │  │  │  │
                                        T1 T2 T3 T4  (LEDs)
```

- The **relay** switches the city between the Green Grid (MB102) and State Grid (5V adapter).
- `INA219 Solar` measures the current coming **out of** the MB102 supply.
- `INA219 Load` measures the total current flowing **into** the PCA9685/LED rail.
- The difference tells the AI whether solar is covering load or not.

---

## Setup & Running

### 1. Flash the Arduino

Open `hardware/neo_arduino/neo_arduino.ino` in Arduino IDE.

Install these libraries via **Sketch → Include Library → Manage Libraries**:
- `Adafruit PWM Servo Driver Library`
- `Adafruit INA219`
- `Adafruit BMP085 Unified` (covers BMP180)
- `DHT sensor library` (Adafruit)
- `LiquidCrystal I2C` (Frank de Brabander)

Select **Board: Arduino Uno** and the correct COM port, then upload.

Open Serial Monitor at 9600 baud — you should see CSV lines like:
```
512,25.0,1013.2,0.00,0.00,512,512,0,0
```

### 2. Install Python Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Set Environment Variables

**Windows (Command Prompt):**
```cmd
set NEO_SERIAL_PORT=COM3
set K2_API_KEY=your_k2_key_here
set EIA_API_KEY=your_eia_key_here
```

**Mac / Linux:**
```bash
export NEO_SERIAL_PORT=/dev/tty.usbmodemXXXX
export K2_API_KEY=your_k2_key_here
export EIA_API_KEY=your_eia_key_here
```

> Find your Arduino's COM port in Arduino IDE under **Tools → Port**.

### 4. Test the Dashboard (no Arduino needed)

```bash
python frontend/dashboard.py
```

This runs a simulated data feed so you can verify the layout before demo day.

### 5. Test the EIA Client

```bash
python backend/eia_client.py
```

Should print live retail price and US grid demand, then a sample price table.

### 6. Run NEO

```bash
cd backend
python main.py
```

The dashboard will take over the terminal. The Arduino LEDs will start responding
within 2 seconds of K2's first API response.

---

## AI Decision Logic (K2 Think V2)

K2 is called every **2 seconds** (not every 100 ms — API budget management).
Between K2 calls, the last command is replayed at full 100 ms rate.

> ⚠️ K2 Think V2 is a **reasoning model**. It prefixes every response with a
> `<think>…</think>` block. `main.py` automatically strips this before parsing
> the JSON command. Do not remove the `strip_think_tags()` function.

### Reward Score

| Event | Points |
|-------|--------|
| Hospital (T1) dimmed 1% | −1000 |
| Utility (T2) dimmed 10% | −50 |
| Residential mismatch 10% | −20 |
| Commercial dimmed 10% | −5 |
| Relay switches ON | −500 |
| Commercial LED on (per sec) | +10 |

### Mayor Policy Buttons

| Button | Policy | Effect |
|--------|--------|--------|
| 1 | Industrial Curfew | T2 penalty weight × 0.5 |
| 2 | Solar Subsidy | AI treats SoC as +20% higher |
| 3 | Brownout Protocol | T3 can drop to 50% penalty-free |
| 4 | Emergency Grid | Relay penalty ignored this cycle |
| 5 | Commercial Lockdown | T4 forced to 0 immediately |

### Earthquake Lockdown

If the tilt switch fires:
- T1 = 255, T2 = 255 (critical services full power)
- T3 = 128 (residential half power)
- T4 = 0 (commercial shut down)
- Relay = 1 (State Grid — stability paramount)
- LCD = `SEISMIC LOCKDOWN`

---

## API Keys

| Key | Where to get |
|-----|-------------|
| `K2_API_KEY` | K2 Think sponsor table at YHack |
| `EIA_API_KEY` | Register free at https://www.eia.gov/opendata/ — instant approval |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Cannot open serial port` | Check `NEO_SERIAL_PORT`, close Arduino IDE Serial Monitor |
| CSV parse errors in console | Open Serial Monitor — check Arduino is sending 9 comma-separated values |
| All LEDs stuck at safe-mode brightness | K2 API failing — check `K2_API_KEY` and internet connection |
| INA219 reads 0 mA | Check I2C address jumpers are soldered correctly |
| LCD shows garbage | Try changing LCD address from `0x27` to `0x3F` in the `.ino` |
| BMP180 pressure always 1013.25 | `bmp.begin()` failed — check SDA/SCL wiring |
| Dashboard not rendering | Run `pip install rich>=13.7.0` |
| EIA returns no data | API key not set, or EIA is down — system falls back to simulated price automatically |