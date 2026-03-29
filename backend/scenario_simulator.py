# ============================================================
#  NEO — Nodal Energy Oracle
#  backend/scenario_simulator.py  —  Monte Carlo Scenario Generation
#  YHack 2025
#
#  Generates multiple plausible future scenarios with probabilities.
#  Shows K2 the range of possible outcomes, enabling Bayesian reasoning.
#
#  Scenarios vary based on:
#    - Storm probability (affects solar drop rate)
#    - Demand patterns (peak load vs. baseline)
#    - Load volatility (unpredictable spikes)
#
#  K2 reasons: "If I dim T4 now, scenario A has 80% success,
#   scenario B has 60%, weighted outcome is 75%."
# ============================================================

import math
import random
from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class Scenario:
    """Represents one plausible future outcome."""
    name: str
    probability: float  # 0.0 to 1.0
    description: str
    battery_in_5m_percent: float  # Predicted SoC after 5 minutes
    battery_in_10m_percent: float  # Predicted SoC after 10 minutes
    relay_needed_in_5m: bool  # Would relay activation be necessary?
    solar_available_in_5m: float  # Predicted solar power (mA)
    load_predicted_in_5m: float  # Predicted load (mA)
    confidence: float  # How confident is this scenario? 0.0-1.0
    action_recommendation: str  # What should K2 do?
    risk_level: str  # "low" / "medium" / "high"


class ScenarioSimulator:
    """Generates Monte Carlo scenarios for multi-outcome reasoning."""
    
    def __init__(
        self,
        battery_capacity_mah: float = 2000.0,
        battery_min_relay_threshold: float = 0.05,
    ):
        self.battery_capacity_mah = battery_capacity_mah
        self.battery_min_relay_threshold = battery_min_relay_threshold
    
    def predict_battery_delta(
        self,
        solar_ma: float,
        load_ma: float,
        time_minutes: float,
    ) -> float:
        """
        Predict battery SOC change over time (in percentage points).
        
        Delta SOC = (net_current_mA * time_minutes) / (capacity_mAh * 60)
        """
        net_ma = solar_ma - load_ma
        delta_soc = (net_ma * time_minutes) / (self.battery_capacity_mah / 100.0)
        return delta_soc
    
    def generate_scenarios(
        self,
        battery_soc: float,
        storm_probability: float,
        solar_ma: float,
        load_ma: float,
        temp_c: float,
        market_price: float,
        t2_demand_factor: float,
        time_horizon_minutes: float = 5.0,
    ) -> List[Scenario]:
        """
        Generate 3-5 plausible scenarios based on current conditions.
        
        Each scenario varies key assumptions (storm intensity, demand spike, etc.)
        weighted by their probability.
        """
        scenarios: List[Scenario] = []
        
        # ─── SCENARIO 1: Clear Skies (best case) ───────────────────────────────
        clear_sky_prob = max(0.0, 1.0 - storm_probability)
        if clear_sky_prob > 0.05:
            # Assume solar stays stable or increases slightly (sunrise effect)
            solar_5m = solar_ma * 1.05
            
            # Assume load stays baseline
            load_5m = load_ma * 0.98
            
            battery_delta_5m = self.predict_battery_delta(solar_5m, load_5m, 5.0)
            battery_delta_10m = self.predict_battery_delta(solar_5m, load_5m, 10.0)
            battery_5m = battery_soc + battery_delta_5m / 100.0
            battery_10m = battery_soc + battery_delta_10m / 100.0
            
            scenarios.append(Scenario(
                name="Clear Skies",
                probability=round(clear_sky_prob, 2),
                description="Weather stable, solar strong, normal load",
                battery_in_5m_percent=round(battery_5m * 100, 1),
                battery_in_10m_percent=round(battery_10m * 100, 1),
                relay_needed_in_5m=battery_5m < self.battery_min_relay_threshold,
                solar_available_in_5m=round(solar_5m, 1),
                load_predicted_in_5m=round(load_5m, 1),
                confidence=0.9,
                action_recommendation="Keep T4 normal brightness; harvest solar",
                risk_level="low",
            ))
        
        # ─── SCENARIO 2: Partial Storm (moderate case) ────────────────────────
        partial_prob = storm_probability * 0.6
        if partial_prob > 0.05:
            # Solar drops by 30-50% due to cloud cover
            solar_5m = solar_ma * random.uniform(0.5, 0.7)
            
            # Load might spike due to weather (AC, heat, lights)
            load_spike_5m = load_ma * random.uniform(1.1, 1.3)
            
            battery_delta_5m = self.predict_battery_delta(solar_5m, load_spike_5m, 5.0)
            battery_delta_10m = self.predict_battery_delta(solar_5m, load_spike_5m, 10.0)
            battery_5m = battery_soc + battery_delta_5m / 100.0
            battery_10m = battery_soc + battery_delta_10m / 100.0
            
            relay_risk = battery_5m < self.battery_min_relay_threshold * 1.5
            
            scenarios.append(Scenario(
                name="Partial Storm",
                probability=round(partial_prob, 2),
                description="Clouds moving in, solar dropping, load spiking",
                battery_in_5m_percent=round(battery_5m * 100, 1),
                battery_in_10m_percent=round(battery_10m * 100, 1),
                relay_needed_in_5m=relay_risk,
                solar_available_in_5m=round(solar_5m, 1),
                load_predicted_in_5m=round(load_spike_5m, 1),
                confidence=0.7,
                action_recommendation="Dim T4 to 40% to pre-charge; prepare relay as fallback",
                risk_level="medium",
            ))
        
        # ─── SCENARIO 3: Severe Storm (worst case) ────────────────────────────
        severe_prob = storm_probability * 0.35
        if severe_prob > 0.05:
            # Solar crashes by 60-80% (heavy clouds)
            solar_5m = solar_ma * random.uniform(0.2, 0.4)
            
            # Load spikes hard (emergency systems, compressors)
            load_spike_5m = load_ma * random.uniform(1.5, 2.0)
            
            battery_delta_5m = self.predict_battery_delta(solar_5m, load_spike_5m, 5.0)
            battery_delta_10m = self.predict_battery_delta(solar_5m, load_spike_5m, 10.0)
            battery_5m = battery_soc + battery_delta_5m / 100.0
            battery_10m = battery_soc + battery_delta_10m / 100.0
            
            scenarios.append(Scenario(
                name="Severe Storm",
                probability=round(severe_prob, 2),
                description="Heavy cloud cover, critical solar loss, extreme load",
                battery_in_5m_percent=round(max(0, battery_5m * 100), 1),
                battery_in_10m_percent=round(max(0, battery_10m * 100), 1),
                relay_needed_in_5m=True,  # Relay is almost certainly needed
                solar_available_in_5m=round(solar_5m, 1),
                load_predicted_in_5m=round(load_spike_5m, 1),
                confidence=0.6,
                action_recommendation="Relay click MANDATORY; Dim T4 to 0; keep T1/T2 full",
                risk_level="high",
            ))
        
        # ─── SCENARIO 4: Demand Spike (unexpected load surge) ──────────────────
        if random.random() < 0.3:  # 30% chance of unpredicted spike
            spike_prob = 0.25
            
            # Solar stays similar
            solar_5m = solar_ma
            
            # Load suddenly increases (industrial process, AC kicking on)
            load_spike_5m = load_ma * random.uniform(1.4, 1.8)
            
            battery_delta_5m = self.predict_battery_delta(solar_5m, load_spike_5m, 5.0)
            battery_delta_10m = self.predict_battery_delta(solar_5m, load_spike_5m, 10.0)
            battery_5m = battery_soc + battery_delta_5m / 100.0
            battery_10m = battery_soc + battery_delta_10m / 100.0
            
            scenarios.append(Scenario(
                name="Demand Spike",
                probability=round(spike_prob, 2),
                description="Unexpected load surge (AC/compressor start)",
                battery_in_5m_percent=round(battery_5m * 100, 1),
                battery_in_10m_percent=round(battery_10m * 100, 1),
                relay_needed_in_5m=battery_5m < self.battery_min_relay_threshold,
                solar_available_in_5m=round(solar_5m, 1),
                load_predicted_in_5m=round(load_spike_5m, 1),
                confidence=0.5,
                action_recommendation="Dim T4 immediately; conserve battery for T1/T2",
                risk_level="high",
            ))
        
        # Normalize probabilities to sum to 1.0
        total_prob = sum(s.probability for s in scenarios)
        if total_prob > 0:
            for scenario in scenarios:
                scenario.probability = round(scenario.probability / total_prob, 2)
        
        return scenarios
    
    def compute_weighted_outcome(self, scenarios: List[Scenario]) -> Dict:
        """
        Compute probability-weighted summary of all scenarios.
        
        This is what K2 uses to make decisions: weighted average of outcomes.
        """
        if not scenarios:
            return {
                "expected_battery_5m": 0.0,
                "relay_probability": 0.0,
                "confidence": 0.0,
                "recommendation": "Insufficient data",
            }
        
        expected_battery = sum(
            s.battery_in_5m_percent * s.probability
            for s in scenarios
        )
        
        relay_prob = sum(
            (1.0 if s.relay_needed_in_5m else 0.0) * s.probability
            for s in scenarios
        )
        
        avg_confidence = sum(
            s.confidence * s.probability
            for s in scenarios
        )
        
        # Determine dominant scenario
        dominant = max(scenarios, key=lambda s: s.probability)
        
        return {
            "expected_battery_5m_percent": round(expected_battery, 1),
            "relay_probability": round(relay_prob, 2),
            "average_confidence": round(avg_confidence, 2),
            "dominant_scenario": dominant.name,
            "dominant_probability": round(dominant.probability, 2),
            "recommendation": dominant.action_recommendation,
        }
    
    def get_scenario_narrative(self, scenarios: List[Scenario]) -> str:
        """
        Generate human-readable summary of scenarios for K2's reasoning.
        
        Shows judges what possible futures K2 is considering.
        """
        if not scenarios:
            return "No scenarios generated."
        
        lines = ["=== POSSIBLE FUTURES (next 5 minutes) ==="]
        for i, scenario in enumerate(scenarios, 1):
            lines.append(
                f"{i}. {scenario.name} ({scenario.probability*100:.0f}% likely): "
                f"Battery → {scenario.battery_in_5m_percent:.0f}%, "
                f"Relay: {'YES' if scenario.relay_needed_in_5m else 'NO'}, "
                f"Risk: {scenario.risk_level}"
            )
        
        weighted = self.compute_weighted_outcome(scenarios)
        lines.append("")
        lines.append(f"Expected battery: {weighted['expected_battery_5m_percent']:.1f}%")
        lines.append(f"Relay probability: {weighted['relay_probability']*100:.0f}%")
        lines.append(f"Action: {weighted['recommendation']}")
        
        return "\n".join(lines)
