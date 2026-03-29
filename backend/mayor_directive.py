#!/usr/bin/env python3
# ============================================================
#  NEO — Nodal Energy Oracle
#  backend/mayor_directive.py  —  Mayor Directive Handler
#  YHack 2025
#
#  Handles natural language directives from the mayor UI and
#  instructs K2 Think V2 on how to adjust power allocation.
# ============================================================

from typing import Any
import json

# K2's personality and directive understanding
DIRECTIVE_SYSTEM_PROMPT = """
You are NEO, the AI grid manager, taking direct instructions from the Mayor.

The Mayor may give you various power directives like:
- "Heat emergency - cool the city at all costs"
- "Industrial curfew - factories shut down"
- "Rolling blackout warning - save the grid"
- "Solar subsidy event - maximize commercial revenue"
- Or anything else they think of

Your job: take their directive and explain how you will adjust power allocation
across the 4 tiers (T1: Hospitals, T2: Utilities, T3: Residential, T4: Commercial)
to serve their goals.

RESPOND IN JSON ONLY:
{
  "interpretation": "what the directive means",
  "strategy": "how you'll adjust power (20-30 words)",
  "tier_adjustments": {
    "T1": "stay critical care only - always 255",
    "T2": "increase/maintain/decrease based on directive",
    "T3": "residential impact",
    "T4": "commercial impact"
  },
  "expected_outcome": "what happens to the grid",
  "warning": "any risks to this approach"
}
"""


def parse_mayor_directive(directive: str, current_state: dict[str, Any]) -> dict[str, Any]:
    """
    Parse a mayor's natural language directive and return power allocation strategy.
    
    Parameters
    ----------
    directive : str
        Mayor's natural language instruction (e.g., "Heat emergency")
    current_state : dict
        Current NEO state (battery, load, storm probability, etc.)
    
    Returns
    -------
    dict with K2's interpretation and recommended power strategy
    """
    # For now, return a deterministic response based on keyword matching
    # In production, this would call K2 Think V2
    
    directive_lower = directive.lower()
    
    # Pre-built responses for common directives
    if any(word in directive_lower for word in ['blackout', 'warning', 'crisis', 'conserve', 'emergency']):
        return {
            "interpretation": "Rolling blackout warning - aggressive conservation",
            "strategy": "Extreme dimming of non-critical loads, protect hospitals and utilities only",
            "tier_adjustments": {
                "T1": "Maintain 255 (hospitals must survive at all costs)",
                "T2": "Maintain 255 (utilities critical for infrastructure)",
                "T3": "Reduce to 50 (minimal residential lighting only)",
                "T4": "Reduce to 0 (commercial completely dark)",
            },
            "expected_outcome": "Severe conservation. Commercial dark, residential minimal. Battery protected.",
            "warning": "Massive penalty for T3 and T4 dimming, but relay cost avoided.",
        }
    
    elif any(word in directive_lower for word in ['heat', 'hot', 'ac', 'cool']):
        return {
            "interpretation": "Heatwave - maximize residential AC and utilities",
            "strategy": "Increase T2 and T3 to max despite load, dim T4 commercial hard",
            "tier_adjustments": {
                "T1": "Maintain 255 (hospitals always critical)",
                "T2": "Increase to 255 (utilities maxed for cooling infrastructure)",
                "T3": "Increase to 255 (residential AC demand critical)",
                "T4": "Reduce to 50-100 (commercial dimmed to free capacity)",
            },
            "expected_outcome": "Battery drains faster but citizens stay cool. May need relay.",
            "warning": "Aggressive dimming of commercial tier costs revenue.",
        }
    
    elif any(word in directive_lower for word in ['curfew', 'factories', 'industrial']):
        return {
            "interpretation": "Industrial curfew - shut down factory load",
            "strategy": "Reduce T2 demand, reallocate to residential and recharge battery",
            "tier_adjustments": {
                "T1": "Maintain 255 (hospitals unaffected)",
                "T2": "Reduce to 100-150 (factories offline, minimal utilities)",
                "T3": "Increase to 255 (freed capacity goes to residential)",
                "T4": "Increase to 255 (freed capacity goes to commercial revenue)",
            },
            "expected_outcome": "Battery SoC climbs. Grid gains breathing room.",
            "warning": "None - this is a relief directive.",
        }
    
    elif any(word in directive_lower for word in ['solar', 'subsidy', 'renewable']):
        return {
            "interpretation": "Solar subsidy event - maximize renewable usage",
            "strategy": "Treat battery as fuller, delay relay, maximize T4 commercial revenue",
            "tier_adjustments": {
                "T1": "Maintain 255 (hospitals)",
                "T2": "Maintain 255 (utilities)",
                "T3": "Maintain current (residential stable)",
                "T4": "Increase to 255 (commercial maximized for revenue during subsidy)",
            },
            "expected_outcome": "Score climbs faster. T4 revenue gain. Battery drain slower.",
            "warning": "Only effective during high solar hours - don't rely after sunset.",
        }
    
    elif any(word in directive_lower for word in ['earthquake', 'seismic', 'lockdown']):
        return {
            "interpretation": "Emergency lockdown - prioritize critical infrastructure",
            "strategy": "Activate relay, lock down T1/T2 at max, minimize civilian load",
            "tier_adjustments": {
                "T1": "Maintain 255 (hospitals critical)",
                "T2": "Maintain 255 (utilities critical)",
                "T3": "Reduce to 100 (residential minimal)",
                "T4": "Reduce to 0 (commercial disabled)",
            },
            "expected_outcome": "Grid provides essential services only. Relay may activate automatically.",
            "warning": "This should trigger tilt sensor lockdown automatically.",
        }
    
    else:
        # Generic response for unknown directives
        return {
            "interpretation": f"Custom directive: {directive}",
            "strategy": "Awaiting specific power tier guidance",
            "tier_adjustments": {
                "T1": "Maintain 255 (hospitals always critical)",
                "T2": "Monitor for directive-specific changes",
                "T3": "Adjust based on context",
                "T4": "Evaluate revenue vs. conservation tradeoff",
            },
            "expected_outcome": "Grid responds to directive guidance",
            "warning": "K2 requires clarification on specific tier targets.",
        }


def format_response_for_chat(directive_analysis: dict[str, Any]) -> str:
    """
    Format K2's directive analysis into a human-readable chat message.
    """
    msg = f"""
Power allocation strategy for directive '{directive_analysis['interpretation']}':

STRATEGY: {directive_analysis['strategy']}

TIER CHANGES:
  • T1 Hospitals: {directive_analysis['tier_adjustments']['T1']}
  • T2 Utilities: {directive_analysis['tier_adjustments']['T2']}
  • T3 Residential: {directive_analysis['tier_adjustments']['T3']}
  • T4 Commercial: {directive_analysis['tier_adjustments']['T4']}

EXPECTED OUTCOME: {directive_analysis['expected_outcome']}

⚠ WARNING: {directive_analysis['warning']}
    """
    return msg.strip()


if __name__ == "__main__":
    # Test with sample directives
    test_directives = [
        "Heat emergency - prioritize residential AC",
        "Industrial curfew after 10pm",
        "Rolling blackout warning",
        "Solar subsidy event",
        "Earthquake lockdown",
        "Increase commercial brightness",
    ]
    
    for directive in test_directives:
        result = parse_mayor_directive(directive, {})
        print(f"\nDirective: {directive}")
        print(f"Response: {format_response_for_chat(result)}")
        print("-" * 60)
