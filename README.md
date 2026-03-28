# ⚡ NEO — Nodal Energy Oracle
### YHack 2025

A hardware-in-the-loop simulation of an autonomous smart city power grid.
An AI agent (K2 Think V2) acts as a grid operator — balancing volatile solar energy,
human demand, and corporate profit in real-time on a physical Arduino breadboard.

---

## Team Roles

| Role | Owner | Files |
|------|-------|-------|
| **Firmware Engineer** | Jeffery | `hardware/neo_arduino/neo_arduino.ino` |
| **AI / Backend Engineer** | Turtle | `backend/main.py`, `backend/eia_client.py` |
| **Data & Dashboard Engineer** | Andrew | `frontend/dashboard.py`, `backend/eia_client.py` |

### Role Breakdown

#### 🔧 Firmware Engineer (Jeffery)
You own everything that touches physical hardware.
- Write and flash `neo_arduino.ino` to the Arduino Uno
- Verify each sensor reads correctly (print raw CSV to Serial Monitor first)
- Confirm the PCA9685 drives all 16 LED channels
- Test relay switching between the two power rails
- Own the I2C address map — solder the INA219 jumpers correctly (see Wiring below)

#### 🧠 AI / Backend Engineer (Turtle)
You own the Python control loop and the K2 API.
- Run `backend/main.py` — this is the brain of the whole system
- Set your `K2_API_KEY` and `NEO_SERIAL_PORT` env vars before running
- Tune `PENALTY_WEIGHTS` to make the reward function feel right
- Tune `SYSTEM_PROMPT` if K2 is making bad decisions
- Handle edge cases: what if K2 returns malformed JSON? (fallback is already coded)

#### 📊 Data & Dashboard Engineer (Andrew)
You own real-world data and visualization.
- Set your `EIA_API_KEY` env var and run `python backend/eia_client.py` to self-test
- Run `python frontend/dashboard.py` standalone to verify the layout looks good
- The dashboard runs as a background thread — `update_state()` is called by `main.py`
- If EIA API is down during the demo, the system automatically falls back to simulated prices

---

## Project Structure

```
neo/
├── hardware/
│   └── neo_arduino/
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