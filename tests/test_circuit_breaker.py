"""Tests for circuit breaker."""
from __future__ import annotations

import time

from agents.circuit_breaker import (
    CircuitBreakerRegistry,
    CircuitState,
    ModelCircuitBreaker,
    NoOpBreaker,
)


class TestNoOpBreaker:
    def test_never_trips(self) -> None:
        breaker = NoOpBreaker()
        assert breaker.check() is True
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        breaker.record_failure()
        assert breaker.check() is True

    def test_methods_noop(self) -> None:
        breaker = NoOpBreaker()
        breaker.record_success()
        breaker.record_failure()
        breaker.record_timeout()
        assert breaker.state == CircuitState.CLOSED


class TestModelCircuitBreaker:
    def test_starts_closed(self) -> None:
        breaker = ModelCircuitBreaker(model_id="test-model", consecutive_threshold=3)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.check() is True

    def test_records_success_resets_failures(self) -> None:
        breaker = ModelCircuitBreaker(model_id="test-model", consecutive_threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.failure_count == 2
        breaker.record_success()
        assert breaker.failure_count == 0

    def test_trips_after_threshold_failures(self) -> None:
        breaker = ModelCircuitBreaker(model_id="test-model", consecutive_threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        assert breaker.check() is False

    def test_resets_after_timeout(self) -> None:
        """After reset_seconds, OPEN → HALF_OPEN."""
        breaker = ModelCircuitBreaker(
            model_id="test-model",
            consecutive_threshold=2,
            reset_seconds=0.05,
        )
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.06)
        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.check() is True  # HALF_OPEN allows probe

    def test_success_in_half_open_resets_to_closed(self) -> None:
        breaker = ModelCircuitBreaker(
            model_id="test-model",
            consecutive_threshold=1,
            reset_seconds=0.05,
        )
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.06)
        assert breaker.state == CircuitState.HALF_OPEN

        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_failure_in_half_open_goes_back_to_open(self) -> None:
        breaker = ModelCircuitBreaker(
            model_id="test-model",
            consecutive_threshold=2,
            reset_seconds=0.05,
        )
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.06)
        assert breaker.state == CircuitState.HALF_OPEN

        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_reset_manually(self) -> None:
        breaker = ModelCircuitBreaker(model_id="test-model", consecutive_threshold=2)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_record_timeout_records_failure(self) -> None:
        breaker = ModelCircuitBreaker(model_id="test-model", consecutive_threshold=1)
        breaker.record_timeout()
        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 1

    def test_stats(self) -> None:
        breaker = ModelCircuitBreaker(
            model_id="test-model",
            consecutive_threshold=3,
            reset_seconds=300,
        )
        breaker.record_success()
        breaker.record_failure()
        breaker.record_failure()
        stats = breaker.stats()

        assert stats["model_id"] == "test-model"
        assert stats["state"] == "closed"
        assert stats["consecutive_failures"] == 2
        assert stats["total_failures"] == 2
        assert stats["total_successes"] == 1
        assert stats["threshold"] == 3
        assert stats["reset_seconds"] == 300

    def test_threshold_of_1_trips_immediately(self) -> None:
        breaker = ModelCircuitBreaker(model_id="fast-fail", consecutive_threshold=1)
        assert breaker.state == CircuitState.CLOSED
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerRegistry:
    def test_get_creates_new(self) -> None:
        registry = CircuitBreakerRegistry()
        breaker = registry.get("model-a")
        assert breaker.model_id == "model-a"
        assert breaker.state == CircuitState.CLOSED

    def test_get_returns_same(self) -> None:
        registry = CircuitBreakerRegistry()
        b1 = registry.get("model-a")
        b2 = registry.get("model-a")
        assert b1 is b2

    def test_register_with_custom_params(self) -> None:
        registry = CircuitBreakerRegistry()
        breaker = registry.register("model-a", threshold=5, reset_seconds=600)
        assert breaker.consecutive_threshold == 5
        assert breaker.reset_seconds == 600

    def test_register_overwrites(self) -> None:
        registry = CircuitBreakerRegistry()
        registry.get("model-a")  # creates default
        registry.register("model-a", threshold=1, reset_seconds=10)
        breaker = registry.get("model-a")
        assert breaker.consecutive_threshold == 1

    def test_all_stats(self) -> None:
        registry = CircuitBreakerRegistry()
        registry.get("model-a")
        registry.get("model-b")
        stats = registry.all_stats()
        assert "model-a" in stats
        assert "model-b" in stats
        assert len(stats) == 2

    def test_reset_all(self) -> None:
        registry = CircuitBreakerRegistry()
        b1 = registry.register("model-a", threshold=2)
        b2 = registry.register("model-b", threshold=2)
        b1.record_failure()
        b1.record_failure()
        assert b1.state == CircuitState.OPEN

        b2.record_failure()
        b2.record_failure()
        assert b2.state == CircuitState.OPEN

        registry.reset_all()
        assert b1.state == CircuitState.CLOSED
        assert b2.state == CircuitState.CLOSED
