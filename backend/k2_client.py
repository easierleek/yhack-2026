# ============================================================
#  NEO — Nodal Energy Oracle
#  backend/k2_client.py  —  K2 API with Circuit Breaker
#  YHack 2025
#
#  Resilient K2 Think V2 client with:
#    - Exponential backoff on failures
#    - Circuit breaker pattern (stop after N failures)
#    - Last valid response caching
#    - Detailed error tracking
# ============================================================

import time
import json
from dataclasses import dataclass
from typing import Optional, Tuple
from openai import OpenAI, APIError, APIConnectionError, RateLimitError

from logger import logger


@dataclass
class K2Response:
    """Parsed K2 response."""
    success: bool
    pwm: list  # 16 PWM values
    relay: int  # 0 or 1
    lcd_text: str
    raw_response: str
    error: Optional[str] = None
    cached: bool = False


class CircuitBreaker:
    """Simple circuit breaker pattern."""
    
    def __init__(self, failure_threshold: int = 3, timeout_sec: float = 60.0):
        self.failure_threshold = failure_threshold
        self.timeout_sec = timeout_sec
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # "closed" (OK) or "open" (failing)
    
    def record_failure(self):
        """Record a failure and update state."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warn(
                f"[K2] Circuit breaker OPEN after {self.failure_count} failures",
                event_type="circuit_breaker_open",
                failure_count=self.failure_count,
            )
    
    def record_success(self):
        """Record a success and reset."""
        self.failure_count = 0
        self.state = "closed"
    
    def can_attempt(self) -> bool:
        """Check if we should attempt a call."""
        if self.state == "closed":
            return True
        
        # Circuit is open; check if timeout expired
        if self.last_failure_time and time.time() - self.last_failure_time > self.timeout_sec:
            self.state = "closed"  # Reset after timeout
            self.failure_count = 0
            logger.info(
                "[K2] Circuit breaker reset after timeout",
                event_type="circuit_breaker_reset",
            )
            return True
        
        return False


class K2Client:
    """K2 Think V2 client with resilience patterns."""
    
    def __init__(self, api_key: str, base_url: str = "https://api.k2think.ai/v1", model: str = "MBZUAI-IFM/K2-Think-v2"):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.circuit_breaker = CircuitBreaker(failure_threshold=3, timeout_sec=30.0)
        
        self.last_valid_response: Optional[K2Response] = None
        self.call_count = 0
        self.error_count = 0
    
    def call(self, system_prompt: str, user_context: dict, max_retries: int = 2) -> K2Response:
        """
        Call K2 with exponential backoff and circuit breaker.
        
        Returns K2Response (either success or cached fallback).
        """
        self.call_count += 1
        
        # Check circuit breaker
        if not self.circuit_breaker.can_attempt():
            logger.warn(
                "[K2] Circuit breaker OPEN; using cached response",
                event_type="k2_circuit_breaker_blocking",
            )
            if self.last_valid_response:
                return K2Response(
                    success=False,
                    pwm=self.last_valid_response.pwm,
                    relay=self.last_valid_response.relay,
                    lcd_text=f"[FALLBACK] {self.last_valid_response.lcd_text}",
                    raw_response=self.last_valid_response.raw_response,
                    error="Circuit breaker open (API unavailable)",
                    cached=True,
                )
            else:
                return self._safe_default_response("Circuit breaker open; no cached response")
        
        # Exponential backoff retry loop
        for attempt in range(max_retries):
            try:
                logger.log_k2_call(user_context, len(system_prompt))
                
                start_time = time.time()
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(user_context, default=str)},
                    ],
                    temperature=0.7,
                    max_tokens=500,
                    timeout=10.0,
                )
                latency_ms = (time.time() - start_time) * 1000
                
                response_text = response.choices[0].message.content
                logger.log_k2_response(response_text, [], 0, latency_ms)
                
                # Parse response
                result = self._parse_response(response_text)
                result.cached = False
                
                # Record success
                self.circuit_breaker.record_success()
                self.last_valid_response = result
                
                return result
            
            except (APIConnectionError, APIError, RateLimitError) as e:
                self.error_count += 1
                self.circuit_breaker.record_failure()
                
                is_last_attempt = (attempt == max_retries - 1)
                error_msg = str(e)
                
                logger.log_k2_error(
                    error_msg,
                    retry_count=attempt + 1,
                    circuit_open=self.circuit_breaker.state == "open",
                )
                
                if is_last_attempt:
                    # All retries exhausted
                    if self.last_valid_response:
                        logger.warn(
                            "[K2] All retries failed; using cached response",
                            event_type="k2_all_retries_failed",
                            attempts=max_retries,
                        )
                        return K2Response(
                            success=False,
                            pwm=self.last_valid_response.pwm,
                            relay=self.last_valid_response.relay,
                            lcd_text=f"[CACHED] {self.last_valid_response.lcd_text}",
                            raw_response=self.last_valid_response.raw_response,
                            error=error_msg,
                            cached=True,
                        )
                    else:
                        return self._safe_default_response(f"K2 API error (no cache): {error_msg}")
                
                # Exponential backoff before retry
                backoff_sec = 2 ** attempt  # 1s, 2s, 4s...
                logger.debug(
                    f"[K2] Backoff {backoff_sec}s before retry {attempt + 2}/{max_retries}",
                    event_type="k2_backoff",
                    backoff_sec=backoff_sec,
                    attempt=attempt + 1,
                )
                time.sleep(backoff_sec)
            
            except Exception as e:
                self.error_count += 1
                error_msg = f"Unexpected error: {str(e)}"
                
                logger.error(
                    f"[K2] Unexpected error: {error_msg}",
                    event_type="k2_unexpected_error",
                )
                
                if self.last_valid_response:
                    return K2Response(
                        success=False,
                        pwm=self.last_valid_response.pwm,
                        relay=self.last_valid_response.relay,
                        lcd_text=f"[ERROR] {self.last_valid_response.lcd_text}",
                        raw_response=self.last_valid_response.raw_response,
                        error=error_msg,
                        cached=True,
                    )
                return self._safe_default_response(error_msg)
        
        # Should not reach here
        return self._safe_default_response("Unknown K2 error")
    
    def _parse_response(self, response_text: str) -> K2Response:
        """Extract PWM, relay, LCD from K2 response."""
        try:
            # Try to extract JSON from response
            start_idx = response_text.find("{")
            end_idx = response_text.rfind("}") + 1
            
            if start_idx == -1 or end_idx <= start_idx:
                return K2Response(
                    success=False,
                    pwm=[128] * 16,
                    relay=0,
                    lcd_text="No JSON found",
                    raw_response=response_text,
                    error="No JSON in response",
                )
            
            json_str = response_text[start_idx:end_idx]
            data = json.loads(json_str)
            
            # Extract fields
            pwm = data.get("pwm", [128] * 16)
            if len(pwm) < 16:
                pwm = pwm + [128] * (16 - len(pwm))
            pwm = pwm[:16]
            
            relay = int(data.get("relay", 0))
            lcd_text = data.get("lcd_text", "NEO Active")
            
            return K2Response(
                success=True,
                pwm=pwm,
                relay=relay,
                lcd_text=lcd_text,
                raw_response=response_text,
            )
        
        except Exception as e:
            return K2Response(
                success=False,
                pwm=[128] * 16,
                relay=0,
                lcd_text="Parse error",
                raw_response=response_text,
                error=f"Parse failed: {str(e)}",
            )
    
    def _safe_default_response(self, error_msg: str) -> K2Response:
        """Return a safe default response when K2 is unavailable."""
        return K2Response(
            success=False,
            pwm=[64] * 16,  # Dim everything
            relay=0,
            lcd_text="[FALLBACK] K2 Unavailable",
            raw_response="",
            error=error_msg,
            cached=False,
        )
    
    def get_stats(self) -> dict:
        """Return call statistics."""
        return {
            "total_calls": self.call_count,
            "errors": self.error_count,
            "success_rate": (self.call_count - self.error_count) / max(1, self.call_count),
            "circuit_breaker_state": self.circuit_breaker.state,
            "circuit_breaker_failures": self.circuit_breaker.failure_count,
            "has_cached_response": self.last_valid_response is not None,
        }
