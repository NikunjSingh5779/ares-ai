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

    def test_delete_does_not_raise_on_redis_error(self) -> None:
        ks = KillSwitch(redis_client=self._failing_redis())
        ks._delete("any_key")  # should not raise

    def test_is_active_returns_false_on_redis_error(self) -> None:
        ks = KillSwitch(redis_client=self._failing_redis())
        assert not ks.is_active

    def test_triggered_by_returns_none_on_redis_error(self) -> None:
        ks = KillSwitch(redis_client=self._failing_redis())
        assert ks.triggered_by is None

    def test_triggered_at_returns_none_on_redis_error(self) -> None:
        ks = KillSwitch(redis_client=self._failing_redis())
        assert ks.triggered_at is None

    def test_activate_not_stored_when_redis_configured_and_failing(self) -> None:
        """When Redis is configured but unavailable, _set returns False so the
        activate() guard ``if self._set(..., nx=True)`` prevents writing to
        in-memory state. This is by design: mixing Redis and in-memory state
        would be inconsistent. Use in-memory mode (no Redis client) for
        test fixtures that need activate to work without Redis."""
        ks = KillSwitch(redis_client=self._failing_redis())
        ks.activate(reason="test")
        # Not stored because _set returns False when Redis fails
        assert not ks.is_active

    def test_activate_without_redis_stores_in_memory(self) -> None:
        """Without a Redis client, activate stores state in memory."""
        ks = KillSwitch()
        ks.activate(reason="test")
        assert ks.is_active
        assert ks.triggered_by == "test"

    def test_arm_clears_in_memory_state(self) -> None:
        ks = KillSwitch()
        ks.activate(reason="test")
        ks.arm()
        assert not ks.is_active


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
        ks._mem["ares:kill_switch:timestamp"] = b"2024-01-01T00:00:00+00:00"
        # _get returns the raw value from _mem (bytes) without decoding
        ts = ks._get("ares:kill_switch:timestamp")
        assert isinstance(ts, bytes)
        result = ks.triggered_at
        assert result is not None
        assert result.year == 2024
