# NEO ML Agent — Quick Reference Guide

## What Makes This Actually ML (Not Just Code)?

**The key insight**: K2 doesn't follow a decision tree. It receives **raw sensor data + economic constraints** and must **reason about tradeoffs**.

```python
# ❌ NOT ML — hardcoded rule
if storm_probability > 0.7:
    t4_pwm = 40  # HARDCODED

# ✓ ACTUAL ML — raw signals to reasoning engine
context = {
    "storm_probability": 0.82,
    "ttd_seconds": 45.0,
    "battery_soc": 0.15,
    "relay_penalty": 500,
    "t4_dim_cost": 3060,
    # ... let K2 figure it out
}
```

K2 thinks: *"Battery dies in 45 sec. If I dim T4 to 80 PWM now, I lose revenue. But if I wait and click relay, that costs -500 pts. Is dimming cheaper?"*

---

## Weather Signals That Drive Power Allocation

| Signal | Source | Meaning | K2 Decision |
|--------|--------|---------|------------|
| `storm_probability` | Pressure + light slope | Clouds incoming → solar about to drop | Pre-charge battery? |
| `solar_time_remaining` | Light slope extrapolation | How many seconds of daylight left | Dim to harvest more before dark? |
| `ttd_seconds` | Battery model physics | When does battery empty at current load | Emergency action needed? |
| `t2_demand_factor` | Temperature thresholds | Industry load multiplier (heat/cold) | Expect higher drain? |
| `market_penalty_active` | Price > $2/kWh | Relay activation is expensive now | Avoid relay at all costs? |

---

## K2 Reasoning Template (What It Actually Does)

```
Given:
  - storm_probability = 0.72
  - solar_time_remaining = 45 sec
  - ttd_seconds = 2400 sec
  - battery_soc = 0.20
  - relay_penalty = -500 pts
  - t4_dim_cost = -3060 pts/sec

K2 must decide:
  1. Is battery low? (20% = yes, be cautious)
  2. Will solar die? (45 sec = YES, very soon)
  3. Is a storm coming? (72% prob = yes, maybe)
  4. How much do I dim?
     - Goal: build charge before solar dies + storm hits
     - Cost: revenue loss from dimming
     - Benefit: survive the storm + sunset without relay
     - Decision: PWM = ?
```

**This is actual reasoning**, not table lookups.

---

## Physics Models (Impressive Parts)

### Time-to-Deficit (Battery Physics)
```
TTD = (battery_capacity × soc) / (load_ma - solar_ma)

Example:
  battery: 2000 mAh × 20% = 400 mAh available
  load: 150 mA
  solar: 80 mA
  drain: 70 mA
  
TTD = 400 / 70 = 5.7 hours

→ If solar dies before 5.7 hours, relay activates
→ K2 must decide: dim now to charge, or keep revenue?
```

### Storm Detection (Dual Redundancy)
```
Input: Last 10 sensor samples

Pressure slope:
  - Each sample: 100ms apart
  - Slope = (pressure_now - pressure_10_samples_ago) / 10
  - Falling pressure = strongest storm indicator
  - Factor: 65% weight (slow but reliable)

Light slope:
  - Each sample: 100ms apart
  - Slope = (light_now - light_10_samples_ago) / 10
  - Darkening = clouds already incoming
  - Factor: 35% weight (fast but noisy)

Result:
  storm_prob = 0.65 × pressure_factor + 0.35 × light_factor
  → Combines two independent signals for robustness
```

### Solar Exhaustion Prediction
```
Q: How many seconds until LDR reads ≈0 (sunset)?

Method:
  1. Measure light slope: -20 units/sample (darkening)
  2. Current light: 100 units
  3. Time to zero: 100 / 20 = 5 samples × 0.1 sec/sample = 0.5 seconds

→ K2 knows: "Solar dies in 0.5 seconds — dim NOW"
```

---

## Test Results (What Passed)

```
✓ Storm detection: Combines pressure + light (dual redundancy)
✓ Battery physics: Drain rate * time = correct
✓ Solar depletion: Slope extrapolation accurate
✓ Temperature scaling: 1.0× (moderate) to 1.5× (extreme)
✓ Economic optimization: Cost-benefit analysis works
✓ K2 integration: Receives raw signals, not pre-computed decisions
✓ Reward structure: Aligns incentives (T1 >> T4)
✓ Safety: Hard overrides for hospitals
✓ Robustness: Handles K2 token exhaustion
✓ Extreme scenario: All signals fire simultaneously

All 10 test suites: PASSED ✓
```

---

## What Gets Sent to K2 (Abbreviated)

```json
{
  "storm_probability": 0.72,
  "solar_time_remaining": 45.2,
  "ttd_seconds": 2400.0,
  "t2_demand_factor": 1.20,
  "mins_to_demand_spike": 5.2,
  "battery_soc": 0.20,
  "market_penalty_active": false,
  "breakeven_ttd": 120.5
}
```

**Key**: These are **raw measurements + physics results**, not "dim T4 to X" commands.

---

## What K2 Produces (Example)

```json
{
  "pwm": [255, 255, 220, 220, 220, 150, 150, 150, 150, 150, 120, 120, 120, 120, 120, 120],
  "relay": 0,
  "lcd_line1": "SOC:20% $1.22",
  "lcd_line2": "Solar:45s T4:47%",
  "reasoning": "Solar dying + storm incoming: pre-dim to charge battery"
}
```

K2 decided: "Solar ends in 45 sec + storm might hit. Keep T4 at 120 PWM to charge before solar fully depletes."

---

## Control Loop Timing

```
100 ms target cycle:
  ├─ 0–10 ms: Read serial, parse sensor CSV
  ├─ 10–20 ms: Update battery model, record history
  ├─ 20–30 ms: Run forecaster (if available)
  ├─ 30–50 ms: Build K2 context JSON
  ├─ 50–100 ms: Wait for K2 response (if 2 sec interval passed)
  └─ 100ms: Write command to Arduino, pace loop
```

**K2 calls happen every 2 seconds** (rate-limited via `K2_CALL_INTERVAL`)
**Falls back to safe command if K2 unreachable**

---

## Deployment Checklist

- [ ] Set `K2_API_KEY` in `.env` file
- [ ] Set `NEO_SERIAL_PORT` to Arduino serial port (e.g., `COM3`)
- [ ] Optional: Set `EIA_API_KEY` for real market price (else uses simulation)
- [ ] Optional: Set `SIM_SPEED=60` to run 60× real-time
- [ ] Run: `python backend/main.py`
- [ ] Monitor: Dashboard at `http://localhost:5000` (if enabled)

---

## Why This Works (Technically)

1. **No Hardcoded Rules**: K2 sees physics + economics, not decision trees
2. **Weather Actually Matters**: Storm/solar signals directly affect battery TTD, which K2 must reason about
3. **Multi-Signal Fusion**: Pressure + light redundancy prevents false alarms
4. **Real Hardware**: 100 ms loops, actual power constraints, serial communication
5. **Fail-Safe**: If K2 crashes, system continues with safe fallback
6. **Aligned Incentives**: Reward function makes the right decisions profitable

---

## Advanced: How Weather Variation Becomes Decisions

**Scenario**: Storm incoming + solar fading + battery at 20%

```
K2 sees:
  storm_probability = 0.82 (HIGH)
  solar_time_remaining = 45 sec (URGENT)
  ttd_seconds = 2400 sec (40 min = borderline)
  battery_soc = 0.20 (low, but not critical)

K2 reasons:
  "Solar dies in 45 seconds. Storm is 82% likely.
   If I keep T4 bright:
     - Lose revenue: +10 pts/sec
     - But drain battery faster
     - If storm hits while empty: can't charge → relay click = -500 pts
   
   If I dim T4 to 60 PWM now:
     - Lose revenue: 10 × 0.76 = 7.6 pts/sec
     - Lose dim penalty: 5 × (1 - 0.6) ^ 0.76 ≈ 2pts/sec
     - Gain: pre-charge battery before solar dies + storm hits
     - If storm doesn't hit: wasted revenue
     - If storm hits and I'm charged: saved the grid
   
   Decision: Dim T4 to 80 PWM (middle ground)"

K2 outputs: [255, 255, 220, 220, 220, 140, 140, 140, 140, 140, 80, 80, 80, 80, 80, 80]
```

**This is actual reasoning through weather variables**, not blindly following rules.

---

## Files Modified

```
backend/
  ├─ main.py                  (K2 prompt, context building, control loop)
  ├─ forecaster.py            (raw signal generation)
  ├─ test_ml_agent.py         ✓ All tests pass
  └─ policy_engine.py         (no changes needed)

NEW:
  └─ TECHNICAL_ARCHITECTURE.md (this file's long version)
```

---

## Next Steps (Optional Enhancements)

- [ ] Real EIA API integration (currently simulated)
- [ ] Dashboard real-time charts (partially implemented)
- [ ] Policy Engine testing (button scenarios)
- [ ] Hardware stress testing (10+ hour runs)
- [ ] K2 temperature sweep (validate reasoning across scenarios)

---

## TL;DR

✓ K2 gets **raw weather signals** (storm probability, solar time remaining, battery physics)
✓ K2 **must reason** about economic tradeoffs (dim now vs. relay later)
✓ K2 **doesn't follow rules**, it **optimizes reward** given constraints
✓ System passes **10 comprehensive tests** validating physics + economics
✓ **Technically impressive** because it's coherent, not complex
