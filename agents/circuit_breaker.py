"""Per-model circuit breaker for LLM API calls.

Implements the RELIABILITY section requirements:
- Track recent failure/429 rate per model
- Trip the breaker after N consecutive failures
- Skip straight to fallback instead of retrying a dead model
"""

from __future__ import annotations

import enum
import time
from typing import Any


class CircuitState(str, enum.Enum):
    CLOSED = "closed"       # Normal operation — requests pass through
    OPEN = "open"           # Tripped — fast-fail without attempting
    HALF_OPEN = "half_open" # Probing — allow one request to test recovery


class NoOpBreaker:
    """Circuit breaker that never trips. Used when no breaker is configured."""

    def record_success(self) -> None: ...
    def record_failure(self) -> None: ...
    def record_timeout(self) -> None: ...
    def check(self) -> bool: return True
    @property
    def state(self) -> CircuitState: return CircuitState.CLOSED
    @property
    def failure_count(self) -> int: return 0


class ModelCircuitBreaker:
    """Tracks consecutive failures per model.

    After `consecutive_threshold` failures in a row, trips OPEN.
    After `reset_seconds` seconds in OPEN state, transitions to HALF_OPEN.
    A single success in HALF_OPEN resets to CLOSED.
    A single failure in HALF_OPEN goes back to OPEN.
    """

    def __init__(
        self,
        model_id: str,
        consecutive_threshold: int = 3,
        reset_seconds: int = 300,
    ) -> None:
        self.model_id = model_id
        self.consecutive_threshold = consecutive_threshold
        self.reset_seconds = reset_seconds

        self._failures: int = 0
        self._last_failure_time: float = 0.0
        self._state: CircuitState = CircuitState.CLOSED
        self._total_failures: int = 0
        self._total_successes: int = 0

    @property
    def state(self) -> CircuitState:
        self._maybe_transition()
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failures

    def check(self) -> bool:
        """Check if a request should be allowed through.

        Returns True if the breaker is CLOSED or HALF_OPEN (probe allowed).
        Returns False if OPEN (fast-fail).
        """
        self._maybe_transition()
        return self._state != CircuitState.OPEN

    def record_success(self) -> None:
        """Record a successful request."""
        self._failures = 0
        self._total_successes += 1
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed request."""
        self._failures += 1
        self._total_failures += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
        elif self._failures >= self.consecutive_threshold:
            self._state = CircuitState.OPEN

    def record_timeout(self) -> None:
        """Shorthand — record_failure with a timeout presumption."""
        self.record_failure()

    def _maybe_transition(self) -> None:
        """Check if enough time has passed to transition OPEN → HALF_OPEN."""
        if self._state == CircuitState.OPEN and self._last_failure_time > 0:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.reset_seconds:
                self._state = CircuitState.HALF_OPEN

    def reset(self) -> None:
        """Manually reset the breaker."""
        self._failures = 0
        self._state = CircuitState.CLOSED
        self._last_failure_time = 0.0

    def stats(self) -> dict[str, Any]:
        """Get breaker statistics."""
        return {
            "model_id": self.model_id,
            "state": self._state.value,
            "consecutive_failures": self._failures,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "threshold": self.consecutive_threshold,
            "reset_seconds": self.reset_seconds,
        }


class CircuitBreakerRegistry:
    """Manages circuit breakers for all models."""

    def __init__(self) -> None:
        self._breakers: dict[str, ModelCircuitBreaker] = {}

    def get(self, model_id: str) -> ModelCircuitBreaker:
        """Get or create a breaker for a model."""
        if model_id not in self._breakers:
            self._breakers[model_id] = ModelCircuitBreaker(model_id=model_id)
        return self._breakers[model_id]

    def register(self, model_id: str, threshold: int = 3, reset_seconds: int = 300) -> ModelCircuitBreaker:
        """Register a breaker with custom parameters."""
        breaker = ModelCircuitBreaker(
            model_id=model_id,
            consecutive_threshold=threshold,
            reset_seconds=reset_seconds,
        )
        self._breakers[model_id] = breaker
        return breaker

    def all_stats(self) -> dict[str, dict[str, Any]]:
        """Get stats for all breakers."""
        return {mid: b.stats() for mid, b in self._breakers.items()}

    def reset_all(self) -> None:
        """Reset all breakers."""
        for breaker in self._breakers.values():
            breaker.reset()
