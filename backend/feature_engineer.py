# ============================================================
#  NEO — Nodal Energy Oracle
#  backend/feature_engineer.py  —  Advanced Feature Engineering
#  YHack 2025
#
#  Computes statistical features from sensor history:
#    - Volatility (variance over time window)
#    - Momentum (rate of change)
#    - Acceleration (2nd derivative)
#    - Percentile ranks (is reading high/low historically?)
#    - Trend strength (autocorrelation)
#
#  These features give K2 richer context for reasoning.
# ============================================================

import math
from typing import List, Dict, Optional


def _safe_std(values: List[float]) -> float:
    """Compute standard deviation safely."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def _percentile(values: List[float], p: float) -> float:
    """Compute percentile (0-100) of most recent value in a dataset."""
    if not values:
        return 50.0
    sorted_vals = sorted(values)
    recent = values[-1]
    rank = sum(1 for v in sorted_vals if v <= recent) / len(sorted_vals)
    return rank * 100.0


def compute_volatility(history: List[Dict], key: str, window: int = 15) -> float:
    """
    Volatility = standard deviation of readings in recent window.
    
    High volatility = unstable sensor (e.g., flickering light, pressure swings)
    Low volatility = stable sensor
    """
    if len(history) < 2:
        return 0.0
    
    recent = history[-min(window, len(history)):]
    values = [r.get(key, 0) for r in recent]
    
    return _safe_std(values)


def compute_momentum(history: List[Dict], key: str, window: int = 5) -> float:
    """
    Momentum = (current - past) / elapsed_time
    
    Positive momentum = increasing (e.g., pressure rising = good weather)
    Negative momentum = decreasing (e.g., light falling = sunset)
    """
    if len(history) < 2:
        return 0.0
    
    recent = history[-min(window, len(history)):]
    if len(recent) < 2:
        return 0.0
    
    current = recent[-1].get(key, 0)
    past = recent[0].get(key, 0)
    dt = len(recent) - 1
    
    return (current - past) / max(dt, 1)


def compute_acceleration(history: List[Dict], key: str, window: int = 10) -> float:
    """
    Acceleration = change in momentum (2nd derivative)
    
    Positive accel = trend is strengthening
    Negative accel = trend is weakening
    """
    if len(history) < 4:
        return 0.0
    
    recent = history[-min(window, len(history)):]
    if len(recent) < 3:
        return 0.0
    
    # Compute momentum in first half vs second half
    mid = len(recent) // 2
    momentum_early = compute_momentum(recent[:mid], key, mid)
    momentum_late = compute_momentum(recent[mid:], key, len(recent) - mid)
    
    return momentum_late - momentum_early


def compute_autocorrelation(history: List[Dict], key: str, lag: int = 1) -> float:
    """
    Autocorrelation at lag N = correlation of signal with itself shifted by N steps.
    
    Values near 1.0 = strong repeating pattern (e.g., hourly oscillation)
    Values near 0.0 = noise / no pattern
    """
    if len(history) < lag + 2:
        return 0.0
    
    values = [r.get(key, 0) for r in history]
    
    if len(values) < lag + 1:
        return 0.0
    
    # Correlation between x[t] and x[t-lag]
    x = values[:-lag]
    x_lagged = values[lag:]
    
    if len(x) < 2:
        return 0.0
    
    mean_x = sum(x) / len(x)
    mean_x_lag = sum(x_lagged) / len(x_lagged)
    
    numerator = sum((x[i] - mean_x) * (x_lagged[i] - mean_x_lag) for i in range(len(x)))
    denom_x = _safe_std(x)
    denom_y = _safe_std(x_lagged)
    
    if denom_x == 0 or denom_y == 0:
        return 0.0
    
    return numerator / (len(x) * denom_x * denom_y)


def compute_percentile_rank(history: List[Dict], key: str) -> float:
    """
    Percentile rank of most recent reading vs. historical distribution.
    
    0-low percentile = reading is low historically (e.g., low light = night)
    50-mid percentile = reading is average
    100-high percentile = reading is high historically (e.g., high light = noon)
    """
    if len(history) < 2:
        return 50.0
    
    values = [r.get(key, 0) for r in history]
    return _percentile(values, 0.5)


def compute_rate_of_change(history: List[Dict], key: str, compare_window: int = 3) -> float:
    """
    Simple rate of change: (now - past) / time_steps
    
    Used as a simple alternative to momentum.
    """
    if len(history) < compare_window:
        return 0.0
    
    current = history[-1].get(key, 0)
    past = history[-compare_window].get(key, 0)
    
    return (current - past) / compare_window


def compute_trend_strength(history: List[Dict], key: str, window: int = 10) -> float:
    """
    Trend strength = how consistent is the direction of change?
    
    1.0 = perfectly consistent uptrend or downtrend
    0.0 = no trend (oscillating)
    """
    if len(history) < window + 1:
        return 0.0
    
    recent = history[-window:]
    
    # Count direction changes
    deltas = []
    for i in range(1, len(recent)):
        delta = recent[i].get(key, 0) - recent[i-1].get(key, 0)
        deltas.append(1 if delta > 0 else -1 if delta < 0 else 0)
    
    if not deltas:
        return 0.0
    
    # Strength = fraction of consistent direction changes
    sign = deltas[0]
    consistent_count = sum(1 for d in deltas if d == sign)
    
    return consistent_count / len(deltas)


class FeatureEngineer:
    """Computes advanced statistical features from sensor history."""
    
    def __init__(self):
        self.history: List[Dict] = []
    
    def update(self, sensor_dict: Dict):
        """Record a new sensor reading."""
        self.history.append(sensor_dict)
        # Keep last 100 readings for statistics
        if len(self.history) > 100:
            self.history.pop(0)
    
    def compute_all_features(self) -> Dict[str, float]:
        """
        Compute all statistical features and return as dict.
        
        Provides K2 with rich context about sensor stability, trends, and patterns.
        """
        if len(self.history) < 2:
            return {}
        
        features = {}
        
        # Light features (LDR sensor)
        if "light" in self.history[-1]:
            features.update({
                "light_volatility": round(compute_volatility(self.history, "light"), 2),
                "light_momentum": round(compute_momentum(self.history, "light"), 2),
                "light_acceleration": round(compute_acceleration(self.history, "light"), 4),
                "light_percentile": round(compute_percentile_rank(self.history, "light"), 1),
                "light_trend_strength": round(compute_trend_strength(self.history, "light"), 2),
            })
        
        # Pressure features (BMP180 sensor)
        if "pressure_hpa" in self.history[-1]:
            features.update({
                "pressure_volatility": round(compute_volatility(self.history, "pressure_hpa"), 3),
                "pressure_momentum": round(compute_momentum(self.history, "pressure_hpa"), 4),
                "pressure_acceleration": round(compute_acceleration(self.history, "pressure_hpa"), 6),
                "pressure_percentile": round(compute_percentile_rank(self.history, "pressure_hpa"), 1),
                "pressure_trend_strength": round(compute_trend_strength(self.history, "pressure_hpa"), 2),
            })
        
        # Temperature features (DHT11 sensor)
        if "temp_c" in self.history[-1]:
            features.update({
                "temp_volatility": round(compute_volatility(self.history, "temp_c"), 2),
                "temp_momentum": round(compute_momentum(self.history, "temp_c"), 3),
                "temp_percentile": round(compute_percentile_rank(self.history, "temp_c"), 1),
            })
        
        # Battery features
        if "battery_soc" in self.history[-1]:
            features.update({
                "battery_volatility": round(compute_volatility(self.history, "battery_soc"), 3),
                "battery_momentum": round(compute_momentum(self.history, "battery_soc"), 4),
            })
        
        # Solar features
        if "solar_ma" in self.history[-1]:
            features.update({
                "solar_volatility": round(compute_volatility(self.history, "solar_ma"), 1),
                "solar_momentum": round(compute_momentum(self.history, "solar_ma"), 2),
                "solar_percentile": round(compute_percentile_rank(self.history, "solar_ma"), 1),
            })
        
        return features
    
    def get_feature_narrative(self) -> str:
        """
        Generate a human-readable summary of what features indicate.
        
        Helps judges understand what K2 is seeing.
        """
        features = self.compute_all_features()
        if not features:
            return "Insufficient history for feature analysis."
        
        narratives = []
        
        # Light analysis
        if "light_momentum" in features:
            if features["light_momentum"] < -50:
                narratives.append("Light fading rapidly (sunset approaching)")
            elif features["light_momentum"] > 50:
                narratives.append("Light increasing (sunrise or clearing)")
            
            if features["light_volatility"] > 100:
                narratives.append("Light unstable (partial cloud cover)")
        
        # Pressure analysis
        if "pressure_momentum" in features:
            if features["pressure_momentum"] < -0.05:
                narratives.append("Pressure dropping fast (storm incoming)")
            elif features["pressure_momentum"] > 0.05:
                narratives.append("Pressure rising (clearing weather)")
            
            if features["pressure_trend_strength"] > 0.7:
                narratives.append("Consistent pressure trend (weather pattern locked in)")
        
        # Battery analysis
        if "battery_momentum" in features:
            if features["battery_momentum"] < -0.001:
                narratives.append("Battery draining faster than charging")
            elif features["battery_momentum"] > 0.001:
                narratives.append("Battery charging well")
        
        return " | ".join(narratives) if narratives else "Stable conditions"
