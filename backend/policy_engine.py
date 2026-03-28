# ============================================================
#  NEO — Nodal Energy Oracle
#  backend/policy_engine.py  —  Mayor Policy State Machine
#  YHack 2025
#
#  ROLE: AI / Backend Engineer (Turtle) owns this file.
#
#  The Mayor (a human at the demo table) can press one of 5
#  buttons to enact an emergency grid policy.  Each policy:
#    - Has a sim-time duration (auto-expires)
#    - Modifies the active penalty/reward weights that feed
#      both the reward function AND the K2 context
#    - Can be queried for dashboard display
#
#  Usage in main.py
#  ────────────────
#    from policy_engine import PolicyEngine
#
#    engine = PolicyEngine(sim_start=SIM_START, sim_speed=SIM_SPEED)
#
#    # On each loop iteration:
#    if sensor["button"]:
#        name = engine.press(sensor["button"])
#        print(f"Policy enacted: {name}")
#
#    weights = engine.get_weights()   # pass to compute_reward() + forecaster
#    status  = engine.status_dict()   # pass to dashboard update_state()
#
#    # Special overrides to check before sending command to Arduino:
#    if engine.commercial_lockdown_active():
#        for ch in range(10, 16):
#            current_command["pwm"][ch] = 0
#
#    if engine.solar_subsidy_active():
#        effective_soc = min(1.0, battery_soc + 0.20)
# ============================================================

from __future__ import annotations

import time
from typing import Callable, Optional

# ─── BASE PENALTY / REWARD WEIGHTS ───────────────────────────────────────────
# These are the default weights when no policy is active.
# Must stay in sync with the PENALTY_WEIGHTS dict in main.py.
BASE_WEIGHTS: dict[str, float] = {
    "tier1_dim":     -1000.0,   # per 1% reduction — catastrophic
    "tier2_per10":   -50.0,     # per 10% dim below full
    "tier3_outrage": -20.0,     # per 10% mismatch vs potentiometer
    "tier4_per10":   -5.0,      # per 10% dim (buffer tier — minor)
    "relay_click":   -500.0,    # every time relay switches ON
    "tier4_revenue": +10.0,     # per second commercial LEDs are lit
}

# Type alias for a weight modifier function
WeightModFn = Callable[[float], float]

# ─── POLICY REGISTRY ─────────────────────────────────────────────────────────
# Each entry defines:
#   name            Human-readable label shown on LCD and dashboard
#   description     Explanation for the README / demo table
#   duration_sim_s  How long the policy stays active in simulated seconds
#   weight_mods     Dict of weight_key → modifier function (applied in order)
#   context_tweak   Optional dict of extra fields to inject into K2 context

POLICY_REGISTRY: dict[int, dict] = {
    1: {
        "name":           "Industrial Curfew",
        "description":    (
            "Halves the T2 penalty weight — allows AI to dim utilities to "
            "save power without as heavy a score hit."
        ),
        "duration_sim_s": 60,
        "weight_mods": {
            "tier2_per10": lambda w: w * 0.5,
        },
        "context_tweak": {
            "policy_industrial_curfew": True,
        },
    },
    2: {
        "name":           "Solar Subsidy",
        "description":    (
            "Treats virtual battery SoC as +20% higher for this policy "
            "window — AI is more willing to run on solar alone."
        ),
        "duration_sim_s": 30,
        "weight_mods": {},   # No weight change — handled via context_tweak
        "context_tweak": {
            "policy_solar_subsidy":    True,
            "soc_bonus":               0.20,   # main.py adds this to battery_soc
        },
    },
    3: {
        "name":           "Brownout Protocol",
        "description":    (
            "Drastically reduces T3 outrage penalty — AI can let residential "
            "power drop to ~50% without citizen penalty."
        ),
        "duration_sim_s": 60,
        "weight_mods": {
            "tier3_outrage": lambda w: w * 0.25,
        },
        "context_tweak": {
            "policy_brownout_protocol": True,
        },
    },
    4: {
        "name":           "Emergency Grid",
        "description":    (
            "Zeroes the relay click penalty for a short window — AI will "
            "freely use State Grid power for one activation without score hit."
        ),
        "duration_sim_s": 15,   # short — just enough for one relay flip
        "weight_mods": {
            "relay_click": lambda w: 0.0,
        },
        "context_tweak": {
            "policy_emergency_grid": True,
        },
    },
    5: {
        "name":           "Commercial Lockdown",
        "description":    (
            "Forces T4 (commercial) to zero.  Removes both T4 dim penalty "
            "and revenue — pure load shedding mode."
        ),
        "duration_sim_s": 120,
        "weight_mods": {
            "tier4_per10":   lambda w: 0.0,
            "tier4_revenue": lambda w: 0.0,
        },
        "context_tweak": {
            "policy_commercial_lockdown": True,
        },
    },
}


# ─── POLICY ENGINE ────────────────────────────────────────────────────────────

class PolicyEngine:
    """
    Tracks active mayor policies, handles button presses with sim-time
    durations, computes effective penalty weights, and exposes query helpers
    for both the control loop and the dashboard.

    Parameters
    ----------
    sim_start : float
        The value of time.time() at system startup — must match SIM_START
        in main.py so simulated seconds stay in sync.
    sim_speed : float
        Simulated seconds per real second (default 60 — 1 real min = 1 sim hr).
    """

    def __init__(
        self,
        sim_start: float,
        sim_speed: float = 60.0,
    ) -> None:
        self._sim_start: float = sim_start
        self._sim_speed: float = sim_speed

        # btn_id → sim-second at which this policy expires
        self._active: dict[int, float] = {}

        # Full log of all presses (for dashboard reasoning feed)
        self._log: list[dict] = []

    # ── Simulated clock ───────────────────────────────────────────────────────

    def _sim_now(self) -> float:
        """Current simulated second since startup."""
        return (time.time() - self._sim_start) * self._sim_speed

    # ── Button press handler ──────────────────────────────────────────────────

    def press(self, button: int) -> Optional[str]:
        """
        Register a mayor button press.

        If the button maps to a known policy, activates it (or re-arms it
        if it was already active — pressing twice resets the timer).

        Parameters
        ----------
        button : int   Button index 1–5.  0 or unknown values are ignored.

        Returns
        -------
        str   Policy name if activated, None if button is 0 or unknown.
        """
        if button not in POLICY_REGISTRY:
            return None

        pol    = POLICY_REGISTRY[button]
        expiry = self._sim_now() + pol["duration_sim_s"]
        self._active[button] = expiry

        entry = {
            "button":    button,
            "name":      pol["name"],
            "sim_start": self._sim_now(),
            "sim_expiry": expiry,
            "real_ts":   time.time(),
        }
        self._log.append(entry)
        # Keep log bounded
        if len(self._log) > 50:
            self._log.pop(0)

        return pol["name"]

    # ── Expiry ────────────────────────────────────────────────────────────────

    def _expire(self) -> None:
        """Remove any policies whose sim-time expiry has passed."""
        now     = self._sim_now()
        expired = [b for b, exp in self._active.items() if now >= exp]
        for b in expired:
            del self._active[b]

    # ── Weight computation ────────────────────────────────────────────────────

    def get_weights(self) -> dict[str, float]:
        """
        Return the effective penalty/reward weights with all currently
        active policies applied on top of BASE_WEIGHTS.

        Modifier functions are applied in button-number order (lower buttons
        take priority if they conflict).

        Returns
        -------
        dict[str, float]  — ready to pass to compute_reward() and forecaster
        """
        self._expire()
        weights = dict(BASE_WEIGHTS)

        for btn_id in sorted(self._active.keys()):
            mods = POLICY_REGISTRY[btn_id]["weight_mods"]
            for key, fn in mods.items():
                if key in weights:
                    weights[key] = fn(weights[key])

        return weights

    # ── Context tweaks ────────────────────────────────────────────────────────

    def get_context_tweaks(self) -> dict:
        """
        Returns a merged dict of all context_tweak fields from active
        policies.  main.py merges this into the K2 context so the model
        knows exactly which policies are in play.

        If Solar Subsidy is active, the 'soc_bonus' key will be present
        and main.py should add it to battery_soc before building context.
        """
        self._expire()
        tweaks: dict = {}
        for btn_id in sorted(self._active.keys()):
            tweaks.update(POLICY_REGISTRY[btn_id].get("context_tweak", {}))
        return tweaks

    # ── Convenience query methods ─────────────────────────────────────────────

    def is_active(self, button: int) -> bool:
        """True if the policy for `button` is currently active."""
        self._expire()
        return button in self._active

    def solar_subsidy_active(self) -> bool:
        """True if Button 2 (Solar Subsidy) is in effect."""
        return self.is_active(2)

    def commercial_lockdown_active(self) -> bool:
        """
        True if Button 5 (Commercial Lockdown) is in effect.
        main.py should zero all T4 PWM channels when this returns True,
        regardless of what K2 commanded.
        """
        return self.is_active(5)

    def emergency_grid_active(self) -> bool:
        """True if Button 4 (Emergency Grid) is in effect."""
        return self.is_active(4)

    def brownout_active(self) -> bool:
        """True if Button 3 (Brownout Protocol) is in effect."""
        return self.is_active(3)

    def industrial_curfew_active(self) -> bool:
        """True if Button 1 (Industrial Curfew) is in effect."""
        return self.is_active(1)

    def active_names(self) -> list[str]:
        """List of human-readable names of all currently active policies."""
        self._expire()
        return [POLICY_REGISTRY[b]["name"] for b in sorted(self._active.keys())]

    # ── Time remaining ────────────────────────────────────────────────────────

    def sim_seconds_remaining(self, button: int) -> float:
        """
        Returns simulated seconds remaining for the given policy.
        Returns 0.0 if the policy is not active.
        """
        self._expire()
        if button not in self._active:
            return 0.0
        return max(0.0, self._active[button] - self._sim_now())

    def real_seconds_remaining(self, button: int) -> float:
        """
        Returns real-time seconds remaining for the given policy.
        Returns 0.0 if the policy is not active.
        """
        sim_remaining = self.sim_seconds_remaining(button)
        return sim_remaining / max(self._sim_speed, 1.0)

    # ── Status dict (for dashboard) ───────────────────────────────────────────

    def status_dict(self) -> dict:
        """
        Returns a dict describing the current policy state, suitable for
        merging directly into the dashboard update_state() call.

        Keys returned:
            active_policy        str    — name of last-activated policy or "None"
            active_policies      list   — all active policy names
            policy_expires_in    float  — sim-seconds remaining on most recent policy
            policy_real_expires  float  — real-seconds remaining on most recent policy
        """
        self._expire()

        if not self._active:
            return {
                "active_policy":       "None",
                "active_policies":     [],
                "policy_expires_in":   0.0,
                "policy_real_expires": 0.0,
            }

        # Report the most recently pressed (highest log index still active)
        last_btn: Optional[int] = None
        for entry in reversed(self._log):
            if entry["button"] in self._active:
                last_btn = entry["button"]
                break

        if last_btn is None:
            last_btn = max(self._active.keys())

        return {
            "active_policy":       POLICY_REGISTRY[last_btn]["name"],
            "active_policies":     self.active_names(),
            "policy_expires_in":   round(self.sim_seconds_remaining(last_btn),  1),
            "policy_real_expires": round(self.real_seconds_remaining(last_btn), 1),
        }

    # ── Press history ─────────────────────────────────────────────────────────

    def press_log(self) -> list[dict]:
        """
        Returns the full press history as a list of dicts, newest last.
        Each entry has: button, name, sim_start, sim_expiry, real_ts.
        """
        return list(self._log)

    def __repr__(self) -> str:
        self._expire()
        if not self._active:
            return "PolicyEngine(no active policies)"
        names = ", ".join(self.active_names())
        return f"PolicyEngine(active=[{names}])"
