"""Edge-case tests for safety gates — Redis errors, __bool__, __repr__."""

from __future__ import annotations

from unittest.mock import MagicMock

import redis

from live_trading.safety import KillSwitch, SafetyCheckResult


class TestSafetyCheckResultDunder:
    """__bool__ and __repr__ on SafetyCheckResult."""

    def test_bool_true_when_passed(self) -> None:
        assert SafetyCheckResult(passed=True)

    def test_bool_false_when_not_passed(self) -> None:
        assert not SafetyCheckResult(passed=False)

    def test_repr_includes_passed_and_code(self) -> None:
        r = SafetyCheckResult(passed=False, reason="test failure", code="kill_switch")
        s = repr(r)
        assert "passed=False" in s
        assert "kill_switch" in s


class TestKillSwitchRedisErrors:
    """KillSwitch Redis error-handling paths."""

    @staticmethod
    def _failing_redis() -> MagicMock:
        client = MagicMock(spec=redis.Redis)
        client.get.side_effect = redis.ConnectionError()
        client.set.side_effect = redis.ConnectionError()
        client.delete.side_effect = redis.ConnectionError()
        return client

    def test_get_returns_none_on_redis_error(self) -> None:
        ks = KillSwitch(redis_client=self._failing_redis())
        assert ks._get("any_key") is None

    def test_set_returns_false_on_redis_error(self) -> None:
        ks = KillSwitch(redis_client=self._failing_redis())
        assert ks._set("any_key", "value") is False

    def test_delete_returns_false_on_redis_error(self) -> None:
        ks = KillSwitch(redis_client=self._failing_redis())
        assert ks._delete("any_key") is False

    def test_is_active_fails_closed_on_redis_error(self) -> None:
        """A shared-store outage must block orders, never allow them."""
        ks = KillSwitch(redis_client=self._failing_redis())
        assert ks.is_active
        assert not ks.storage_healthy
        assert not ks.check()

    def test_triggered_by_returns_none_on_fresh_redis_error(self) -> None:
        ks = KillSwitch(redis_client=self._failing_redis())
        assert ks.triggered_by is None

    def test_triggered_at_returns_none_on_fresh_redis_error(self) -> None:
        ks = KillSwitch(redis_client=self._failing_redis())
        assert ks.triggered_at is None

    def test_activate_latches_locally_when_redis_configured_and_failing(self) -> None:
        """The trip must still block this process even if Redis is unavailable."""
        ks = KillSwitch(redis_client=self._failing_redis())
        assert ks.activate(reason="test") is False
        assert ks.is_active
        assert ks.triggered_by == "test"
        assert not ks.storage_healthy

    def test_activate_without_redis_stores_in_memory(self) -> None:
        """Without a Redis client, activate stores state in memory."""
        ks = KillSwitch()
        assert ks.activate(reason="test") is True
        assert ks.is_active
        assert ks.triggered_by == "test"

    def test_arm_clears_in_memory_state(self) -> None:
        ks = KillSwitch()
        assert ks.activate(reason="test") is True
        assert ks.arm() is True
        assert not ks.is_active

    def test_arm_refuses_when_redis_is_down(self) -> None:
        """Re-arming must not silently unblock while the store is unavailable."""
        ks = KillSwitch(redis_client=self._failing_redis())
        assert ks.is_active
        assert ks.arm() is False
        assert ks.is_active

    def test_recovery_requires_explicit_arm(self) -> None:
        """A recovered store does not auto-clear a fail-closed latch."""
        client = self._failing_redis()
        ks = KillSwitch(redis_client=client)

        assert ks.is_active  # latches closed

        # Store recovers, but the switch stays latched until a human re-arms.
        client.get.side_effect = None
        client.get.return_value = None
        client.delete.side_effect = None
        client.delete.return_value = 1

        assert ks.is_active
        assert ks.arm() is True
        assert not ks.is_active
        assert ks.storage_healthy

    def test_auto_trigger_fails_closed_on_redis_error(self) -> None:
        ks = KillSwitch(redis_client=self._failing_redis())
        assert ks.auto_trigger(99.0) is True
        assert ks.is_active
        assert ks.triggered_by is not None


class TestKillSwitchRedisBytes:
    """KillSwitch Redis with bytes return values."""

    def test_is_active_with_bytes(self) -> None:
        client = MagicMock(spec=redis.Redis)
        client.get.return_value = b"1"
        ks = KillSwitch(redis_client=client)
        assert ks.is_active

    def test_triggered_by_with_bytes(self) -> None:
        client = MagicMock(spec=redis.Redis)
        client.get.return_value = b"manual"
        ks = KillSwitch(redis_client=client)
        assert ks.triggered_by == "manual"

    def test_triggered_at_with_bytes(self) -> None:
        client = MagicMock(spec=redis.Redis)
        client.get.return_value = b"2024-01-01T00:00:00+00:00"
        ks = KillSwitch(redis_client=client)
        assert ks.triggered_at is not None
        assert ks.triggered_at.year == 2024

    def test_triggered_at_with_string(self) -> None:
        client = MagicMock(spec=redis.Redis)
        client.get.return_value = "2024-06-15T12:30:00+00:00"
        ks = KillSwitch(redis_client=client)
        assert ks.triggered_at is not None
        assert ks.triggered_at.month == 6

    def test_triggered_at_with_raw_bytes_in_memory(self) -> None:
        """Line 134 coverage: _get returns raw bytes from in-memory fallback."""
        ks = KillSwitch()
        # Deliberately inject bytes: Redis returns bytes, and the in-memory
        # fallback must decode them the same way (defensive branch below).
        ks._mem["ares:kill_switch:timestamp"] = b"2024-01-01T00:00:00+00:00"  # type: ignore[assignment]
        # _get returns the raw value from _mem (bytes) without decoding
        ts = ks._get("ares:kill_switch:timestamp")
        assert isinstance(ts, bytes)
        result = ks.triggered_at
        assert result is not None
        assert result.year == 2024
