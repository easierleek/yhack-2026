# ============================================================
#  NEO — Nodal Energy Oracle
#  backend/logger.py  —  Structured Event Logging
#  YHack 2025
#
#  Centralized logging for:
#    - K2 API calls & responses
#    - Policy activations
#    - Relay switches & major decisions
#    - Sensor anomalies & health
#    - Reward scores & trends
# ============================================================

import os
import sys
import json
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Any

# ─── SETUP LOG DIRECTORY ──────────────────────────────────────────────────────
_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

# ─── STRUCTURED LOGGER ─────────────────────────────────────────────────────────
class StructuredLogger:
    """Writes structured JSON logs + console output."""
    
    def __init__(self, name: str = "neo"):
        self.name = name
        self.start_time = time.time()
        
        # Console logger
        self.console_logger = logging.getLogger(name)
        self.console_logger.setLevel(logging.DEBUG)
        
        if not self.console_logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(logging.DEBUG)
            fmt = logging.Formatter(
                "[%(asctime)s] %(levelname)-8s | %(message)s",
                datefmt="%H:%M:%S"
            )
            handler.setFormatter(fmt)
            self.console_logger.addHandler(handler)
        
        # File logger (JSON)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = _LOG_DIR / f"neo_{timestamp}.jsonl"
        self.file_logger = logging.getLogger(f"{name}_file")
        self.file_logger.setLevel(logging.DEBUG)
        
        if not self.file_logger.handlers:
            file_handler = logging.FileHandler(self.log_file)
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter("%(message)s"))
            self.file_logger.addHandler(file_handler)
    
    def _get_elapsed(self) -> float:
        """Seconds since logger creation."""
        return time.time() - self.start_time
    
    def _emit_json(self, event: dict, level: str):
        """Emit JSON-formatted log entry."""
        event.setdefault("timestamp", datetime.now().isoformat())
        event.setdefault("elapsed_s", self._get_elapsed())
        event.setdefault("level", level)
        
        json_str = json.dumps(event, default=str)
        self.file_logger.log(logging.INFO, json_str)
    
    # ─── PUBLIC API ────────────────────────────────────────────────────────────
    
    def info(self, msg: str, **kwargs):
        """Info-level message + JSON fields."""
        self.console_logger.info(msg)
        self._emit_json({"message": msg, **kwargs}, "INFO")
    
    def warn(self, msg: str, **kwargs):
        """Warning-level message + JSON fields."""
        self.console_logger.warning(msg)
        self._emit_json({"message": msg, **kwargs}, "WARN")
    
    def error(self, msg: str, **kwargs):
        """Error-level message + JSON fields."""
        self.console_logger.error(msg)
        self._emit_json({"message": msg, **kwargs}, "ERROR")
    
    def debug(self, msg: str, **kwargs):
        """Debug-level message + JSON fields."""
        self.console_logger.debug(msg)
        self._emit_json({"message": msg, **kwargs}, "DEBUG")
    
    # ─── DOMAIN-SPECIFIC EVENTS ────────────────────────────────────────────────
    
    def log_k2_call(self, context: dict, system_prompt_len: int):
        """Log K2 API invocation."""
        self.info(
            "[K2] Calling K2 Think V2",
            event_type="k2_call",
            context_fields=len(context),
            prompt_chars=system_prompt_len,
            battery_soc=context.get("battery_soc"),
            storm_prob=context.get("storm_probability"),
        )
    
    def log_k2_response(self, response_text: str, pwm_array: list, relay: int, latency_ms: float):
        """Log K2 API response."""
        self.info(
            "[K2] Response received",
            event_type="k2_response",
            latency_ms=latency_ms,
            pwm_mean=sum(pwm_array) / len(pwm_array) if pwm_array else 0,
            relay_state=relay,
            response_chars=len(response_text),
        )
    
    def log_k2_error(self, error_msg: str, retry_count: int, circuit_open: bool):
        """Log K2 API failure."""
        self.warn(
            f"[K2] API error: {error_msg}",
            event_type="k2_error",
            retry_count=retry_count,
            circuit_breaker_open=circuit_open,
        )
    
    def log_policy_activated(self, policy_name: str, button_id: int, duration_sec: float):
        """Log policy button press."""
        self.info(
            f"[POLICY] {policy_name} activated",
            event_type="policy_activated",
            button_id=button_id,
            duration_sec=duration_sec,
        )
    
    def log_relay_switch(self, action: str, reason: str):
        """Log relay switching event."""
        self.info(
            f"[RELAY] {action}",
            event_type="relay_switch",
            action=action,
            reason=reason,
        )
    
    def log_sensor_anomaly(self, sensor_name: str, current_val: float, prev_val: float, issue: str):
        """Log sensor health warning."""
        self.warn(
            f"[SENSOR] {sensor_name}: {issue}",
            event_type="sensor_anomaly",
            sensor=sensor_name,
            current=current_val,
            previous=prev_val,
            issue=issue,
        )
    
    def log_reward_score(self, reward: float, penalties: dict, tier_breakdown: dict):
        """Log reward calculation."""
        self.debug(
            f"[REWARD] Score: {reward:.1f}",
            event_type="reward_score",
            total_reward=reward,
            penalties=penalties,
            tier_breakdown=tier_breakdown,
        )
    
    def log_loop_timing(self, loop_time_ms: float, k2_call_due: bool, forecast_secs: list):
        """Log control loop performance metrics."""
        self.debug(
            f"[LOOP] {loop_time_ms:.1f}ms",
            event_type="loop_timing",
            loop_ms=loop_time_ms,
            k2_call_due=k2_call_due,
            forecast_mean_ms=sum(forecast_secs) / len(forecast_secs) if forecast_secs else 0,
        )
    
    def log_startup(self, config: dict):
        """Log system startup."""
        self.info(
            "[STARTUP] NEO system initializing",
            event_type="startup",
            serial_port=config.get("serial_port"),
            k2_available=config.get("k2_available"),
            forecaster_available=config.get("forecaster_available"),
            dashboard_available=config.get("dashboard_available"),
            policy_available=config.get("policy_available"),
        )
    
    def log_shutdown(self, reason: str, uptime_sec: float):
        """Log system shutdown."""
        self.info(
            f"[SHUTDOWN] {reason}",
            event_type="shutdown",
            reason=reason,
            uptime_sec=uptime_sec,
        )


# ─── SINGLETON INSTANCE ────────────────────────────────────────────────────────
logger = StructuredLogger("neo")
