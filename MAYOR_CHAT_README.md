# Mayor Chat Bot: Dynamic Power Allocation via Natural Language

**Branch**: `mayor_chat_bot`

Voice your city! The Mayor Chat interface lets you issue power allocation directives in plain English, and NEO's AI explains how it will respond.

## Features

- **Natural Language Input**: Type any power directive you want
- **Movable & Expandable**: Like the existing info card—drag the header, resize from the corner
- **Real-time K2 Explanation**: AI explains its power strategy for each directive
- **Extensible Directives**: 5 built-in scenarios + open-ended custom directives

## Quick Start

### 1. Install Dependencies

```bash
pip install flask
```

### 2. Run the System

The mayor API is automatically started when you run `main.py`:

```bash
python backend/main.py
```

You'll see:
```
[NEO] Mayor API started on http://localhost:5000
```

### 3. Access the Chat

Open the React dashboard at `http://localhost:5173` (or wherever your React dev server runs).

- **Chat FAB Button**: Green speech bubble in the bottom-left corner
- Click to open the mayor chat panel
- Drag the header to move, resize from the bottom-right handle

## Built-In Directives

### 1. **Heat Emergency**
```
User input: "Heat emergency - cool the city"
```
- **Strategy**: Maximize T2 (utilities) and T3 (residential) for AC, dim T4 (commercial)
- **Outcome**: Battery drains faster but everyone stays cool
- **Demo**: Cover the light sensor (hand over LDR) to simulate clouds; watch T4 dim as NEO redirects power to AC

### 2. **Industrial Curfew**
```
User input: "Industrial curfew after 10pm"
```
- **Strategy**: Reduce T2 factory load, reallocate to residential & commercial
- **Outcome**: Battery SoC climbs back up; grid gains breathing room
- **Demo**: Watch battery SoC on dashboard climb as factory load disappears

### 3. **Rolling Blackout Warning**
```
User input: "Rolling blackout warning" or "Conservation mode"
```
- **Strategy**: Extreme conservation—only T1 (hospitals) and T2 (utilities) stay bright
- **Outcome**: T3 and T4 go dark; battery protected at all costs
- **Demo**: Show aggressive dimming of commercial tier to avoid relay cost

### 4. **Solar Subsidy Event**
```
User input: "Solar subsidy event"
```
- **Strategy**: Treat battery as 25% fuller; maximize T4 commercial revenue
- **Outcome**: Score climbs faster during high solar hours
- **Demo**: Watch reward score climb faster; T4 stays bright longer

### 5. **Earthquake Lockdown**
```
User input: "Earthquake" or "Seismic lockdown"
```
- **Strategy**: Emergency mode—T1 and T2 at full, minimal civilian load
- **Outcome**: Grid powers only critical infrastructure
- **Demo**: Shake the breadboard; tilt sensor fires; everything dims except hospitals

## Custom Directives

The system is open-ended. Try:
```
"Increase brightness in residential areas"
"Prioritize schools over commercial"
"Maximize battery charge"
"Prepare for storm approaching"
```

For unrecognized directives, K2 returns:
```
"K2 requires clarification on specific tier targets."
```

You can extend `backend/mayor_directive.py` to add more specific handling.

## Architecture

### Frontend

```
frontend/web/src/components/MayorChat.tsx
├── Message history [MAYOR] vs [NEO]
├── Textarea input (Enter to send, Shift+Enter for newline)
└── Loading state during API call

frontend/web/src/App.tsx
├── Second floating panel (left side, tied to state)
├── FAB button (bottom-left, green chat bubble)
└── All paneling shared with existing info card

frontend/web/src/styles/MayorChat.css
└── Shared charcoal system with NEO status accents
```

### Backend

```
backend/mayor_directive.py
├── parse_mayor_directive(directive, state) → strategy dict
├── Built-in keyword matching (heat, curfew, blackout, solar, earthquake)
└── format_response_for_chat(strategy) → human-readable message

frontend/mayor_api.py
├── Flask REST server on :5000
├── POST /api/mayor-directive
│   ├── Request: { directive: str, current_state: dict }
│   └── Response: { response: str, strategy: dict, interpretation: str }
└── GET /api/health (simple health check)
```

### Integration

```
backend/main.py
├── Imports start_mayor_api from frontend/mayor_api.py
├── Starts it as daemon thread at startup
└── Responds to MayorChat fetch requests in real-time
```

## API Reference

### POST /api/mayor-directive

**Request**:
```json
{
  "directive": "Heat emergency - prioritize residential AC",
  "current_state": { ...full NEO state dict... }
}
```

**Response**:
```json
{
  "response": "Power allocation strategy for...",
  "strategy": {
    "T1": "Maintain 255 (hospitals always critical)",
    "T2": "Increase to 255 (utilities maxed...)",
    "T3": "Increase to 255 (residential AC...)",
    "T4": "Reduce to 50-100 (commercial dimmed...)"
  },
  "interpretation": "Heatwave - maximize residential AC and utilities"
}
```

### GET /api/health

Simple health check.

**Response**:
```json
{
  "status": "ok",
  "service": "neo-mayor-api"
}
```

## Demo Script (90 Seconds)

Perfect for impressing judges with rapid decision-making:

1. **Start normal operation** (10 sec)
   - Dashboard shows T4 commercial bright, score climbing
   - "Grid operating normally, all tiers balanced"

2. **Issue heat emergency** (15 sec)
   - Type: "Heat emergency"
   - Watch T4 dim immediately on dashboard
   - AI explains: "Redirecting to residential AC"

3. **Simulate solar loss** (10 sec)
   - Cover the LDR with your hand
   - Solar on dashboard → 0 mA
   - Battery starts draining faster

4. **Issue blackout warning** (15 sec)
   - Type: "Rolling blackout warning"
   - Watch T3 and T4 go nearly dark
   - AI explains: "Extreme conservation mode activated"

5. **Trigger earthquake** (20 sec)
   - Shake the breadboard gently
   - Tilt sensor fires
   - Everything dims except hospitals
   - LCD flashes "SEISMIC LOCKDOWN"
   - Type: "Earthquake lockdown" in chat
   - AI confirms: "Emergency infrastructure protection engaged"

6. **Recover** (10 sec)
   - Remove hand from LDR
   - Solar returns, battery climbing
   - AI autonomously recovers grid to balanced state

**Total**: 80 seconds of decision-making visibility. Judges see:
- ✅ Real-time AI reasoning to natural language input
- ✅ Multi-tier power allocation tradeoffs
- ✅ Hardware responsiveness (LED dimming, LCD, relay)
- ✅ Autonomous recovery after crisis

## Troubleshooting

### "ERROR: Failed to process directive. Check that mayor_api.py is running..."

1. Verify Flask is installed: `pip install flask`
2. Check if mayor_api server is running: `curl http://localhost:5000/api/health`
3. Look for errors in terminal where `main.py` is running

### "K2 requires clarification..."

This means the directive doesn't match any built-in keywords. Either:
- Try a keyword phrase (heat, curfew, blackout, solar, earthquake)
- Or extend `parse_mayor_directive()` in `backend/mayor_directive.py` to handle it

### Chat not appearing on dashboard

1. Make sure you're on the `mayor_chat_bot` branch: `git branch | grep mayor`
2. Check React build included the new components: look for `MayorChat.tsx` in build output
3. Clear browser cache (Ctrl+Shift+Delete) and reload

## Files Changed / Created

**New Files**:
- `frontend/web/src/components/MayorChat.tsx` — React chat component
- `frontend/web/src/styles/MayorChat.css` — Chat styling
- `backend/mayor_directive.py` — Directive parsing logic
- `frontend/mayor_api.py` — Flask REST API

**Modified Files**:
- `frontend/web/src/App.tsx` — Added MayorChat integration
- `frontend/web/src/App.css` — Chat FAB & panel styles
- `backend/main.py` — Starts mayor_api server

## Next Steps (Post-Hackathon)

- Transform `parse_mayor_directive()` to call actual K2 Think V2 (currently uses pattern matching)
- Add directive history saving to SQLite
- Implement "undo" / "revert to previous state" functionality
- Add slider inputs for granular T1/T2/T3/T4 target PWM levels
- Multi-language support (translate directives to Spanish, Mandarin, etc.)

---

**Questions?** See `mayor_directive.py` docstrings or ask a team member!
