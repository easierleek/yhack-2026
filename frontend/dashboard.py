# ============================================================
#  NEO — Nodal Energy Oracle
#  dashboard.py  —  Rich Terminal Dashboard
#  YHack 2025
#
#  ROLE: Data & Dashboard Engineer owns this file.
#
#  Runs in a background daemon thread.  The main control loop
#  calls  update_state(dict)  after every cycle; the dashboard
#  re-renders at ~4 Hz automatically.
#
#  Layout (80-col terminal minimum, 120-col recommended)
#  ┌─────────────────────────────────────────────────────────┐
#  │  ⚡ NEO — Nodal Energy Oracle  |  AI reasoning line      │
#  ├──────────────┬──────────────┬──────────────────────────┤
#  │  Grid State  │   Sensors    │      LED Tiers            │
#  ├──────────────┴──────────────┴──────────────────────────┤
#  │                  AI Reasoning Feed                       │
#  ├─────────────────────────────────────────────────────────┤
#  │           EIA Live Data  |  Policy  |  Warnings         │
#  └─────────────────────────────────────────────────────────┘
#
#  Install:  pip install rich
# ============================================================

from __future__ import annotations

import threading
import time
import collections
from typing import Any

# ─── WebSocket broadcast (optional — web UI) ──────────────────────────────────
try:
    from frontend.ws_server import ws_broadcast as _ws_broadcast
except ImportError:
    try:
        from ws_server import ws_broadcast as _ws_broadcast
    except ImportError:
        _ws_broadcast = None

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule
from rich import box

# ─── SHARED STATE ─────────────────────────────────────────────────────────────
# main.py calls update_state() after every control cycle.

_state_lock = threading.Lock()
_state: dict[str, Any] = {
    # Grid
    "battery_soc":    0.5,
    "sim_hour":       0.0,
    "market_price":   1.0,
    "relay":          0,
    "reward_score":   0.0,
    # Sensors
    "light":          512,
    "temp_c":         25.0,
    "pressure_hpa":   1013.25,
    "solar_ma":       0.0,
    "load_ma":        0.0,
    "pot1":           512,
    "pot2":           512,
    "tilt":           0,
    "button":         0,
    # AI
    "reasoning":      "Waiting for first AI cycle...",
    "pwm":            [255, 255, 255, 255, 255,
                       200, 200, 200, 200, 200,
                       128, 128, 128, 128, 128, 128],
    # Slopes / forecast
    "sun_slope":      0.0,
    "pressure_slope": 0.0,
    "duck_demand":    0.5,
    # EIA
    "eia_retail":     0.17,
    "eia_demand_mw":  400_000.0,
    "eia_live":       False,
    "eia_age_s":      0.0,
    # Mayor
    "active_policy":  "None",
    # Warnings / faults
    "fault":          "",
    # Loop timing
    "loop_ms":        0.0,
    "k2_calls":       0,
}

# Circular buffer of the last 18 AI reasoning strings for the feed panel
_reasoning_feed: collections.deque[tuple[float, str]] = collections.deque(maxlen=18)


def update_state(new_state: dict[str, Any]) -> None:
    """Thread-safe state update.  Call from main.py after every cycle."""
    with _state_lock:
        _state.update(new_state)
        reason = new_state.get("reasoning", "")
        if reason and reason != _state.get("_last_reason", ""):
            _state["_last_reason"] = reason
            _reasoning_feed.append((time.time(), reason))
        # Build broadcast payload outside lock to minimise hold time
        broadcast_payload = dict(_state)
        feed_snapshot = list(_reasoning_feed)

    # Broadcast to web UI (non-blocking — drops frame if WS not ready)
    if _ws_broadcast is not None:
        try:
            broadcast_payload["reasoning_feed"] = [
                [ts, text] for ts, text in feed_snapshot
            ]
            _ws_broadcast(broadcast_payload)
        except Exception:
            pass


def _snap() -> dict[str, Any]:
    """Return a shallow copy of the state for rendering (no lock held during render)."""
    with _state_lock:
        return dict(_state)


# ─── RENDER HELPERS ───────────────────────────────────────────────────────────

_POLICY_LABELS = {
    "0": "None",
    "1": "Industrial Curfew",
    "2": "Solar Subsidy",
    "3": "Brownout Protocol",
    "4": "Emergency Grid",
    "5": "Commercial Lockdown",
}

_TIER_DEFS = [
    # (label,   channels,    rich_color,   icon)
    ("T1 Hospitals",  [0, 1],              "white",  "⚪"),
    ("T2 Utilities",  [2, 3, 4],           "red",    "🔴"),
    ("T3 Residential",[5, 6, 7, 8, 9],    "green",  "🟢"),
    ("T4 Commercial", [10, 11, 12, 13, 14, 15], "yellow", "🟡"),
]


def _soc_bar(soc: float, width: int = 12) -> Text:
    filled = round(soc * width)
    bar    = "█" * filled + "░" * (width - filled)
    if soc > 0.55:
        color = "bright_green"
    elif soc > 0.25:
        color = "yellow"
    else:
        color = "bright_red"
    t = Text()
    t.append(bar, style=color)
    t.append(f" {soc * 100:4.1f}%", style="bold " + color)
    return t


def _level_bar(value_0_255: float, color: str, width: int = 12) -> Text:
    pct    = value_0_255 / 255.0
    filled = round(pct * width)
    bar    = "▮" * filled + "▯" * (width - filled)
    t = Text()
    t.append(bar, style=color)
    t.append(f" {pct * 100:5.1f}%", style="dim")
    return t


def _sim_clock(sim_hour: float) -> str:
    h   = int(sim_hour) % 24
    m   = int((sim_hour - int(sim_hour)) * 60)
    tod = "🌙" if h < 6 or h >= 22 else ("🌅" if h < 9 else ("☀️" if h < 18 else "🌆"))
    return f"{tod} {h:02d}:{m:02d}"


def _relay_text(relay: int) -> Text:
    t = Text()
    if relay:
        t.append("⚡ STATE GRID", style="bold red")
    else:
        t.append("☀  SOLAR ONLY", style="bold green")
    return t


def _tilt_text(tilt: int) -> Text:
    t = Text()
    if tilt:
        t.append("🚨 SEISMIC!", style="bold red blink")
    else:
        t.append("✓  Stable", style="green")
    return t


def _slope_arrow(slope: float) -> str:
    if slope > 15:   return "↑↑"
    if slope > 3:    return "↑"
    if slope < -15:  return "↓↓"
    if slope < -3:   return "↓"
    return "→"


# ─── PANEL BUILDERS ───────────────────────────────────────────────────────────

def _build_grid_panel(s: dict) -> Panel:
    t = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    t.add_column("k", style="bold cyan",    no_wrap=True, min_width=13)
    t.add_column("v", style="bright_white", no_wrap=False)

    t.add_row("Battery SoC", _soc_bar(s["battery_soc"]))
    t.add_row("Sim Time",    _sim_clock(s["sim_hour"]))
    t.add_row("Duck Demand", f"{s['duck_demand'] * 100:.0f}% expected")
    t.add_row("Market Price",
              Text(f"${s['market_price']:.2f}/kWh",
                   style="red" if s["market_price"] > 2.0 else
                         ("yellow" if s["market_price"] > 1.2 else "green")))
    t.add_row("Grid Source",  _relay_text(s["relay"]))
    t.add_row("Reward",
              Text(f"{s['reward_score']:+,.0f} pts",
                   style="bright_green" if s["reward_score"] >= 0 else "bright_red"))
    t.add_row("Loop",        f"{s['loop_ms']:.1f} ms  |  K2 calls: {s['k2_calls']}")
    policy = s.get("active_policy", "None")
    t.add_row("Mayor Policy",
              Text(policy, style="bold magenta" if policy != "None" else "dim"))

    return Panel(t, title="[bold blue]Grid State[/]", border_style="blue", padding=(0, 1))


def _build_sensor_panel(s: dict) -> Panel:
    t = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    t.add_column("k", style="bold cyan",    no_wrap=True, min_width=12)
    t.add_column("v", style="bright_white", no_wrap=False)

    # Light with slope arrow
    sun_arrow = _slope_arrow(s["sun_slope"])
    light_pct = s["light"] / 1023 * 100
    t.add_row("Light",
              Text(f"{s['light']:4d}  ({light_pct:.0f}%) {sun_arrow}",
                   style="yellow" if light_pct > 50 else "dim yellow"))

    t.add_row("Temperature",
              Text(f"{s['temp_c']:.1f} °C",
                   style="red" if s["temp_c"] > 28 else "white"))

    pres_arrow = _slope_arrow(s["pressure_slope"] * 1000)   # rescale
    t.add_row("Pressure",
              Text(f"{s['pressure_hpa']:.1f} hPa {pres_arrow}",
                   style="cyan"))

    t.add_row("Solar",  f"{s['solar_ma']:.1f} mA")
    t.add_row("Load",   f"{s['load_ma']:.1f} mA")

    net = s["solar_ma"] - s["load_ma"]
    t.add_row("Net",
              Text(f"{net:+.1f} mA",
                   style="bright_green" if net >= 0 else "bright_red"))

    pot_avg = ((s["pot1"] + s["pot2"]) / 2) / 1023 * 100
    t.add_row("Pot1 / Pot2",
              f"{s['pot1']} / {s['pot2']}  (avg {pot_avg:.0f}%)")

    t.add_row("Seismic",  _tilt_text(s["tilt"]))

    btn = s["button"]
    t.add_row("Button",
              Text(f"#{btn} — {_POLICY_LABELS.get(str(btn), '?')}",
                   style="bold magenta") if btn else Text("—", style="dim"))

    return Panel(t, title="[bold cyan]Sensors[/]", border_style="cyan", padding=(0, 1))


def _build_tiers_panel(s: dict) -> Panel:
    pwm = s.get("pwm", [255] * 16)

    t = Table(box=box.SIMPLE_HEAD, show_header=True, padding=(0, 1), expand=True)
    t.add_column("Tier",   style="bold",         no_wrap=True, min_width=15)
    t.add_column("Avg",    style="bright_white",  no_wrap=True, width=6)
    t.add_column("Level",                          no_wrap=True, min_width=22)

    for label, channels, color, icon in _TIER_DEFS:
        avg_pwm = sum(pwm[c] for c in channels if c < len(pwm)) / len(channels)
        t.add_row(
            f"{icon} {label}",
            f"{avg_pwm:.0f}",
            _level_bar(avg_pwm, color),
        )

    # Per-channel mini grid
    ch_text = Text()
    for i in range(16):
        val  = pwm[i] if i < len(pwm) else 0
        pct  = val / 255.0
        char = "█" if pct > 0.75 else ("▓" if pct > 0.5 else ("░" if pct > 0.1 else " "))
        if i < 2:    ch_text.append(char, style="white")
        elif i < 5:  ch_text.append(char, style="red")
        elif i < 10: ch_text.append(char, style="green")
        else:        ch_text.append(char, style="yellow")
        if i in (1, 4, 9):
            ch_text.append(" │ ", style="dim")

    t.add_row("[dim]CH 0-15[/]", "", ch_text)

    return Panel(t, title="[bold yellow]LED Tiers (PCA9685)[/]", border_style="yellow", padding=(0, 1))


def _build_feed_panel() -> Panel:
    """Scrolling AI reasoning log — newest at bottom."""
    lines = list(_reasoning_feed)   # snapshot, no lock needed for deque reads

    content = Text()
    if not lines:
        content.append("  No AI decisions yet...\n", style="dim italic")
    else:
        for ts, reason in lines:
            elapsed = time.time() - ts
            age_str = f"{elapsed:5.1f}s ago"
            content.append(f"  [{age_str}] ", style="dim cyan")
            content.append(reason + "\n", style="bright_white")

    return Panel(
        content,
        title="[bold magenta]AI Reasoning Feed (K2 Think)[/]",
        border_style="magenta",
        padding=(0, 1),
    )


def _build_footer_panel(s: dict) -> Panel:
    # Three columns: EIA status | Mayor info | Fault / warning
    eia_text = Text()
    if s["eia_live"]:
        eia_text.append("✓ EIA LIVE  ", style="bold green")
    else:
        eia_text.append("⚠ EIA SIMULATED  ", style="bold yellow")
    eia_text.append(
        f"retail={s['eia_retail']:.4f} $/kWh  "
        f"demand={s['eia_demand_mw']:,.0f} MW  "
        f"(age {s['eia_age_s']:.0f}s)",
        style="dim"
    )

    fault = s.get("fault", "")
    fault_text = Text()
    if fault:
        fault_text.append(f"🔴 FAULT: {fault}", style="bold red blink")
    else:
        fault_text.append("✓ No faults", style="dim green")

    policy_text = Text()
    policy = s.get("active_policy", "None")
    if policy != "None":
        policy_text.append(f"📋 Policy active: {policy}", style="bold magenta")
    else:
        policy_text.append("No mayor policy active", style="dim")

    inner = Columns(
        [
            Panel(eia_text,    title="EIA Data",    border_style="dim blue",   padding=(0, 1)),
            Panel(policy_text, title="Mayor",       border_style="dim magenta", padding=(0, 1)),
            Panel(fault_text,  title="Grid Faults", border_style="dim red",    padding=(0, 1)),
        ],
        expand=True,
    )
    return Panel(inner, border_style="dim", padding=(0, 0))


# ─── FULL LAYOUT ──────────────────────────────────────────────────────────────

def _build_layout(s: dict) -> Layout:
    layout = Layout(name="root")

    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main",   ratio=3),
        Layout(name="feed",   ratio=2),
        Layout(name="footer", size=9),
    )

    # Header bar
    ts_str  = time.strftime("%H:%M:%S")
    soc_pct = s["battery_soc"] * 100
    header_text = Text(justify="center")
    header_text.append("⚡ NEO — Nodal Energy Oracle ⚡", style="bold magenta")
    header_text.append(
        f"    SoC: {soc_pct:.1f}%  |  "
        f"Score: {s['reward_score']:+,.0f} pts  |  "
        f"{_sim_clock(s['sim_hour'])}  |  "
        f"Wall: {ts_str}",
        style="dim white",
    )
    layout["header"].update(Panel(header_text, border_style="magenta", padding=(0, 2)))

    # Main row: grid | sensors | tiers
    layout["main"].split_row(
        Layout(_build_grid_panel(s),    name="grid",    ratio=1),
        Layout(_build_sensor_panel(s),  name="sensors", ratio=1),
        Layout(_build_tiers_panel(s),   name="tiers",   ratio=2),
    )

    layout["feed"].update(_build_feed_panel())
    layout["footer"].update(_build_footer_panel(s))

    return layout


# ─── DASHBOARD THREAD ENTRY POINT ─────────────────────────────────────────────

def run_dashboard(refresh_hz: float = 4.0) -> None:
    """
    Blocking call — run in a daemon thread from main.py:

        import threading
        from dashboard import run_dashboard, update_state

        t = threading.Thread(target=run_dashboard, daemon=True)
        t.start()

    Then call update_state({...}) from your control loop.
    """
    console = Console()
    interval = 1.0 / max(1.0, refresh_hz)

    with Live(
        _build_layout(_snap()),
        console=console,
        refresh_per_second=refresh_hz,
        screen=True,          # full-screen takeover
        transient=False,
    ) as live:
        while True:
            try:
                live.update(_build_layout(_snap()))
            except Exception:
                pass   # never crash the dashboard thread
            time.sleep(interval)


# ─── STANDALONE DEMO ──────────────────────────────────────────────────────────
# Run:  python dashboard.py
# Simulates a live feed so you can check layout without the Arduino plugged in.

if __name__ == "__main__":
    import math
    import random

    print("Running dashboard demo (Ctrl-C to quit)...")
    time.sleep(0.5)

    dash_thread = threading.Thread(target=run_dashboard, daemon=True)
    dash_thread.start()

    t0 = time.time()
    score = 0.0
    k2_calls = 0

    while True:
        elapsed = time.time() - t0
        sim_h   = (elapsed * 60 / 3600) % 24   # 1 real-min = 1 sim-hour

        soc    = 0.5 + 0.4 * math.sin(elapsed * 0.3)
        solar  = max(0.0, 200 * math.sin(math.pi * sim_h / 12) + random.gauss(0, 10))
        load   = 180 + 60 * math.sin(elapsed * 0.1) + random.gauss(0, 5)
        score += random.uniform(-8, 12)
        k2_calls += 1 if elapsed % 2 < 0.1 else 0

        pwm_demo = [255, 255]
        pwm_demo += [int(220 + 20 * math.sin(elapsed * 0.5))] * 3
        pwm_demo += [int(150 + 80 * math.sin(elapsed * 0.2 + i)) for i in range(5)]
        pwm_demo += [int(max(0, 200 * math.cos(elapsed * 0.15 + i))) for i in range(6)]

        update_state({
            "battery_soc":    max(0.0, min(1.0, soc)),
            "sim_hour":       sim_h,
            "market_price":   round(1.0 + 1.5 * abs(math.sin(elapsed * 0.08)), 2),
            "relay":          1 if soc < 0.15 else 0,
            "reward_score":   score,
            "light":          int(512 + 400 * math.sin(math.pi * sim_h / 12)),
            "temp_c":         20.0 + 5.0 * math.sin(elapsed * 0.05),
            "pressure_hpa":   1013.0 + 3 * math.sin(elapsed * 0.02),
            "solar_ma":       solar,
            "load_ma":        load,
            "pot1":           int(512 + 400 * math.sin(elapsed * 0.07)),
            "pot2":           int(400 + 300 * math.cos(elapsed * 0.09)),
            "tilt":           1 if 5.0 < (elapsed % 30) < 5.3 else 0,
            "button":         0,
            "sun_slope":      random.gauss(0, 8),
            "pressure_slope": random.gauss(0, 0.3),
            "duck_demand":    0.5 + 0.4 * math.sin(math.pi * sim_h / 12),
            "eia_retail":     0.1723,
            "eia_demand_mw":  421_500.0,
            "eia_live":       True,
            "eia_age_s":      elapsed % 300,
            "active_policy":  "Solar Subsidy" if 10 < (elapsed % 40) < 15 else "None",
            "fault":          "Grid Fault ch3" if 20 < (elapsed % 50) < 21 else "",
            "loop_ms":        random.uniform(95, 115),
            "k2_calls":       k2_calls,
            "pwm":            pwm_demo,
            "reasoning": random.choice([
                "Battery > 80%, solar surplus — keeping T4 bright for revenue.",
                "Pressure dropping — pre-dimming T4 to charge before storm.",
                "Evening peak: market at $2.80/kWh — avoiding relay click.",
                "T3 demand spike detected — matching potentiometer at 78%.",
                "Solar slope negative — 4 min to deficit, dimming T4 now.",
                "Battery critical 8% — flipping relay to State Grid.",
                "Duck curve 7PM spike anticipated — charging buffer now.",
            ]),
        })

        time.sleep(0.1)
