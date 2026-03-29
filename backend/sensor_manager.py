# ============================================================
#  NEO — Nodal Energy Oracle
#  backend/sensor_manager.py  —  Sensor Validation & Health
#  YHack 2025
#
#  Validates sensor readings, detects stuck/anomalous values,
#  and triggers fallback modes if critical sensors fail.
# ============================================================

from typing import Optional, Dict, List
from dataclasses import dataclass
import time


@dataclass
class SensorBounds:
    """Valid range for a sensor."""
    name: str
    min_val: float
    max_val: float
    units: str


# ─── SENSOR BOUNDS ────────────────────────────────────────────────────────────
# Only 3 physical sensors: light, temperature, pressure
SENSOR_BOUNDS = {
    "light_lux": SensorBounds("Light (LUX)", 0, 1023, "lux"),
    "temp_c": SensorBounds("Temperature", -10, 60, "°C"),
    "pressure_hpa": SensorBounds("Pressure", 800, 1100, "hPa"),
}

STUCK_SENSOR_TIMEOUT = 30.0  # seconds of unchanged readings before flagging


class SensorManager:
    """Monitors sensor health and validates readings."""
    
    def __init__(self):
        self.last_readings: Dict[str, float] = {}
        self.last_change_time: Dict[str, float] = {}
        self.anomaly_count: Dict[str, int] = {}
        self.health_status: Dict[str, str] = {}  # "ok", "warn", "fail"
        
        for key in SENSOR_BOUNDS.keys():
            self.last_readings[key] = None
            self.last_change_time[key] = time.time()
            self.anomaly_count[key] = 0
            self.health_status[key] = "unknown"
    
    def validate_reading(self, sensor_key: str, value: float) -> tuple[bool, Optional[str]]:
        """
        Validate a single sensor reading.
        Returns (is_valid, error_message).
        """
        if sensor_key not in SENSOR_BOUNDS:
            return False, f"Unknown sensor: {sensor_key}"
        
        bounds = SENSOR_BOUNDS[sensor_key]
        
        # Out of range check
        if value < bounds.min_val or value > bounds.max_val:
            self.anomaly_count[sensor_key] += 1
            return False, f"{bounds.name} out of range: {value} {bounds.units} (expect {bounds.min_val}–{bounds.max_val})"
        
        return True, None
    
    def check_stuck_sensor(self, sensor_key: str, current_val: float, tolerance: float = 0.1) -> tuple[bool, Optional[str]]:
        """
        Detect if sensor reading is stuck (unchanged for timeout period).
        Returns (is_stuck, warning_message).
        """
        if sensor_key not in self.last_readings:
            return False, None
        
        last_val = self.last_readings[sensor_key]
        time_since_change = time.time() - self.last_change_time[sensor_key]
        
        # Check if value changed
        if last_val is not None and abs(current_val - last_val) > tolerance:
            self.last_change_time[sensor_key] = time.time()
        
        # If stuck for too long, flag it
        if time_since_change > STUCK_SENSOR_TIMEOUT:
            self.health_status[sensor_key] = "warn"
            return True, f"{SENSOR_BOUNDS[sensor_key].name} stuck at {current_val} for {time_since_change:.0f}s"
        
        self.health_status[sensor_key] = "ok"
        return False, None
    
    def update_reading(self, sensor_key: str, value: float) -> dict:
        """
        Update a sensor reading and perform all checks.
        Returns {"valid": bool, "stuck": bool, "errors": [str], "warnings": [str]}
        """
        errors = []
        warnings = []
        
        # Validate range
        is_valid, error_msg = self.validate_reading(sensor_key, value)
        if not is_valid:
            errors.append(error_msg)
            self.health_status[sensor_key] = "fail"
        
        # Check stuck
        is_stuck, warn_msg = self.check_stuck_sensor(sensor_key, value)
        if is_stuck:
            warnings.append(warn_msg)
            self.health_status[sensor_key] = "warn"
        
        # Update last reading
        self.last_readings[sensor_key] = value
        
        return {
            "valid": is_valid,
            "stuck": is_stuck,
            "errors": errors,
            "warnings": warnings,
        }
    
    def preflight_check(self, state: dict) -> tuple[bool, List[str]]:
        """
        Run startup validation on sensor state dict.
        Returns (all_ok, list_of_errors).
        """
        critical_sensors = ["light_lux", "temp_c", "battery_soc"]
        errors = []
        
        for sensor_key in critical_sensors:
            if sensor_key not in state:
                errors.append(f"Missing critical sensor: {sensor_key}")
                continue
            
            val = state[sensor_key]
            is_valid, error_msg = self.validate_reading(sensor_key, val)
            if not is_valid:
                errors.append(error_msg)
        
        return len(errors) == 0, errors
    
    def get_health_report(self) -> dict:
        """
        Return health status for all sensors.
        Format: {"ok": [...], "warn": [...], "fail": [...]}
        """
        report = {"ok": [], "warn": [], "fail": []}
        for sensor, status in self.health_status.items():
            bounds = SENSOR_BOUNDS[sensor]
            entry = f"{bounds.name}: {self.last_readings.get(sensor, 'N/A')} {bounds.units}"
            if status in report:
                report[status].append(entry)
        return report
    
    def any_critical_failures(self) -> bool:
        """Return True if any critical sensor is failing."""
        critical = ["battery_soc", "solar_ma", "load_ma"]
        return any(self.health_status.get(s) == "fail" for s in critical)
