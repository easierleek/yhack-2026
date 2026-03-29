# ============================================================
#  NEO — Nodal Energy Oracle
#  backend/decision_store.py  —  SQLite Decision Logging
#  YHack 2025
#
#  Persistent storage of every K2 decision:
#    - K2 reasoning input (forecast signals)
#    - K2 decision output (PWM, relay)
#    - Resulting reward score
#    - Actual sensor state 5s later
#
#  Enables post-analysis of K2 effectiveness.
# ============================================================

import sqlite3
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import asdict

from logger import logger


class DecisionStore:
    """SQLite store for K2 decisions and outcomes."""
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize SQLite database."""
        if db_path is None:
            db_dir = Path(__file__).parent.parent / "data"
            db_dir.mkdir(exist_ok=True)
            db_path = db_dir / "neo_decisions.db"
        
        self.db_path = Path(db_path)
        self.conn = None
        self._init_db()
    
    def _init_db(self):
        """Create tables if they don't exist."""
        self.conn = sqlite3.connect(str(self.db_path))
        cursor = self.conn.cursor()
        
        # Decisions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                unix_time REAL,
                
                -- Input context (what K2 saw)
                battery_soc REAL,
                storm_probability REAL,
                solar_time_remaining REAL,
                ttd_seconds REAL,
                t2_demand_factor REAL,
                market_penalty_active INTEGER,
                market_price_usd_kwh REAL,
                
                -- K2 decision output
                pwm_t1 INTEGER,
                pwm_t2 INTEGER,
                pwm_t3 INTEGER,
                pwm_t4 INTEGER,
                relay_state INTEGER,
                k2_reasoning TEXT,
                
                -- Immediate reward
                reward_score REAL,
                
                -- Outcome (state 5s after decision)
                outcome_timestamp DATETIME,
                outcome_battery_soc REAL,
                outcome_load_ma REAL,
                outcome_solar_ma REAL,
                
                -- Decision quality
                was_cached INTEGER,
                error_occurred INTEGER,
                error_message TEXT
            )
        """)
        
        # Aggregate metrics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                unix_time REAL,
                
                -- Summary stats
                decisions_since_startup INTEGER,
                avg_reward REAL,
                relay_clicks INTEGER,
                k2_error_count INTEGER,
                k2_cache_rate REAL,
                avg_response_time_ms REAL,
                battery_soc_min REAL,
                battery_soc_max REAL
            )
        """)
        
        self.conn.commit()
        logger.info(
            "[STORE] Decision store initialized",
            event_type="store_init",
            db_path=str(self.db_path),
        )
    
    def log_decision(
        self,
        context: Dict[str, Any],
        k2_response: Any,  # K2Response object
        reward_score: float,
        was_cached: bool = False,
        error_occurred: bool = False,
        error_message: Optional[str] = None,
    ):
        """Log a K2 decision with input context and immediate reward."""
        try:
            cursor = self.conn.cursor()
            now = time.time()
            
            # Extract PWM values (handle both list and dict formats)
            pwm = k2_response.pwm if hasattr(k2_response, 'pwm') else [128] * 16
            pwm_t1 = pwm[0] if len(pwm) > 0 else 128
            pwm_t2 = pwm[5] if len(pwm) > 5 else 128
            pwm_t3 = pwm[10] if len(pwm) > 10 else 128
            pwm_t4 = pwm[15] if len(pwm) > 15 else 128
            
            cursor.execute("""
                INSERT INTO decisions (
                    unix_time, battery_soc, storm_probability, solar_time_remaining,
                    ttd_seconds, t2_demand_factor, market_penalty_active, market_price_usd_kwh,
                    pwm_t1, pwm_t2, pwm_t3, pwm_t4, relay_state, k2_reasoning,
                    reward_score, was_cached, error_occurred, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now,
                context.get("battery_soc"),
                context.get("storm_probability"),
                context.get("solar_time_remaining"),
                context.get("ttd_seconds"),
                context.get("t2_demand_factor"),
                int(context.get("market_penalty_active", False)),
                context.get("market_price_usd_kwh"),
                pwm_t1, pwm_t2, pwm_t3, pwm_t4,
                k2_response.relay if hasattr(k2_response, 'relay') else 0,
                k2_response.raw_response if hasattr(k2_response, 'raw_response') else "",
                reward_score,
                int(was_cached),
                int(error_occurred),
                error_message,
            ))
            
            self.conn.commit()
        
        except Exception as e:
            logger.error(
                f"[STORE] Failed to log decision: {str(e)}",
                event_type="store_error",
            )
    
    def log_outcome(
        self,
        decision_id: int,
        battery_soc: float,
        load_ma: float,
        solar_ma: float,
    ):
        """Log the outcome of a prior decision (5s later)."""
        try:
            cursor = self.conn.cursor()
            now = time.time()
            
            cursor.execute("""
                UPDATE decisions
                SET outcome_timestamp = ?,
                    outcome_battery_soc = ?,
                    outcome_load_ma = ?,
                    outcome_solar_ma = ?
                WHERE id = ?
            """, (datetime.now(), battery_soc, load_ma, solar_ma, decision_id))
            
            self.conn.commit()
        
        except Exception as e:
            logger.error(
                f"[STORE] Failed to log outcome: {str(e)}",
                event_type="store_error",
            )
    
    def log_metrics(self, metrics: Dict[str, Any]):
        """Log aggregate system metrics."""
        try:
            cursor = self.conn.cursor()
            now = time.time()
            
            cursor.execute("""
                INSERT INTO metrics (
                    unix_time, decisions_since_startup, avg_reward, relay_clicks,
                    k2_error_count, k2_cache_rate, avg_response_time_ms,
                    battery_soc_min, battery_soc_max
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now,
                metrics.get("decisions_since_startup", 0),
                metrics.get("avg_reward", 0.0),
                metrics.get("relay_clicks", 0),
                metrics.get("k2_error_count", 0),
                metrics.get("k2_cache_rate", 0.0),
                metrics.get("avg_response_time_ms", 0.0),
                metrics.get("battery_soc_min", 0.0),
                metrics.get("battery_soc_max", 100.0),
            ))
            
            self.conn.commit()
        
        except Exception as e:
            logger.error(
                f"[STORE] Failed to log metrics: {str(e)}",
                event_type="store_error",
            )
    
    def query_decisions(
        self,
        limit: int = 100,
        where_clause: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query recent decisions."""
        try:
            cursor = self.conn.cursor()
            
            query = "SELECT * FROM decisions"
            if where_clause:
                query += f" WHERE {where_clause}"
            query += f" ORDER BY id DESC LIMIT {limit}"
            
            cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            
            return [dict(zip(columns, row)) for row in rows]
        
        except Exception as e:
            logger.error(
                f"[STORE] Query failed: {str(e)}",
                event_type="store_error",
            )
            return []
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        try:
            cursor = self.conn.cursor()
            
            # Count decisions
            cursor.execute("SELECT COUNT(*) FROM decisions")
            total_decisions = cursor.fetchone()[0]
            
            # Avg reward
            cursor.execute("SELECT AVG(reward_score) FROM decisions WHERE reward_score IS NOT NULL")
            avg_reward = cursor.fetchone()[0] or 0.0
            
            # Error rate
            cursor.execute("SELECT COUNT(*) FROM decisions WHERE error_occurred = 1")
            error_count = cursor.fetchone()[0]
            
            # Cache rate
            cursor.execute("SELECT COUNT(*) FROM decisions WHERE was_cached = 1")
            cache_count = cursor.fetchone()[0]
            
            return {
                "total_decisions": total_decisions,
                "avg_reward": avg_reward,
                "error_count": error_count,
                "cache_count": cache_count,
                "cache_rate": cache_count / max(1, total_decisions),
                "error_rate": error_count / max(1, total_decisions),
            }
        
        except Exception as e:
            logger.error(
                f"[STORE] Summary query failed: {str(e)}",
                event_type="store_error",
            )
            return {}
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()


# ─── SINGLETON INSTANCE ────────────────────────────────────────────────────────
_store_instance: Optional[DecisionStore] = None


def get_store() -> DecisionStore:
    """Get or create singleton store instance."""
    global _store_instance
    if _store_instance is None:
        _store_instance = DecisionStore()
    return _store_instance
