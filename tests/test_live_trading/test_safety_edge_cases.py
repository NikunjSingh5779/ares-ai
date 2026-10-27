"""Edge-case tests for safety gates — Redis errors, __bool__, __repr__."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import redis

from live_trading.safety import _ARM_EPOCH_KEY, KillSwitch, SafetyCheckResult


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
        client.pipeline.side_effect = redis.ConnectionError()
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
        client.set.side_effect = None
        client.set.return_value = True
        client.delete.side_effect = None
        client.delete.return_value = 1
        client.pipeline.side_effect = None

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


class _FakePipeline:
    """Pipeline subset used by ``KillSwitch.arm()``."""

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store
        self._ops: list[tuple[str, tuple[str, ...], dict[str, Any]]] = []

    def delete(self, *keys: str) -> _FakePipeline:
        self._ops.append(("delete", keys, {}))
        return self

    def set(self, key: str, value: str, **kwargs: Any) -> _FakePipeline:
        self._ops.append(("set", (key, value), kwargs))
        return self

    def execute(self) -> list[Any]:
        results: list[Any] = []
        for op, args, kwargs in self._ops:
            if op == "delete":
                results.append(sum(1 for key in args if self._store.pop(key, None) is not None))
            else:
                key, value = args
                if kwargs.get("nx") and key in self._store:
                    results.append(False)
                else:
                    self._store[key] = value
                    results.append(True)
        self._ops.clear()
        return results


class _FakeRedis:
    """Tiny shared Redis stand-in; two ``KillSwitch`` instances share it.

    ``down`` makes every command fail like a connection outage.
    ``pipeline_down`` fails only ``pipeline()``, so reads still work.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.down = False
        self.pipeline_down = False

    def get(self, key: str) -> str | None:
        if self.down:
            raise redis.ConnectionError("store down")
        return self.store.get(key)

    def set(self, key: str, value: str, nx: bool = False) -> bool:
        if self.down:
            raise redis.ConnectionError("store down")
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def delete(self, *keys: str) -> int:
        if self.down:
            raise redis.ConnectionError("store down")
        return sum(1 for key in keys if self.store.pop(key, None) is not None)

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        if self.down or self.pipeline_down:
            raise redis.ConnectionError("store down")
        return _FakePipeline(self.store)


class TestKillSwitchSharedArmEpoch:
    """A human re-arm in one process must clear every other process's latch."""

    @staticmethod
    def _client(fake: _FakeRedis) -> redis.Redis:
        return cast(redis.Redis, fake)

    def test_one_shared_arm_clears_a_latched_runner(self) -> None:
        fake = _FakeRedis()
        runner = KillSwitch(redis_client=self._client(fake))
        api = KillSwitch(redis_client=self._client(fake))

        assert not runner.is_active  # healthy: publishes/observes a baseline
        baseline = fake.store[_ARM_EPOCH_KEY]
        assert baseline.startswith("baseline:")

        fake.down = True
        assert runner.is_active  # the outage latches this process
        assert not runner.storage_healthy

        fake.down = False
        assert runner.is_active  # recovery alone never clears the latch
        assert not runner.storage_healthy

        assert api.arm() is True
        assert fake.store[_ARM_EPOCH_KEY].startswith("arm:")
        assert fake.store[_ARM_EPOCH_KEY] != baseline

        assert not runner.is_active  # the shared epoch clears the runner
        assert runner.storage_healthy

    def test_check_stays_blocked_until_the_shared_arm(self) -> None:
        fake = _FakeRedis()
        runner = KillSwitch(redis_client=self._client(fake))
        api = KillSwitch(redis_client=self._client(fake))

        assert not runner.is_active
        fake.down = True
        assert not runner.check()
        fake.down = False
        assert not runner.check()

        assert api.arm() is True
        assert runner.check()

    def test_missing_epoch_token_never_clears_a_latch(self) -> None:
        """A flushed store cannot silently re-enable trading."""
        fake = _FakeRedis()
        ks = KillSwitch(redis_client=self._client(fake))

        assert not ks.is_active
        fake.down = True
        assert ks.is_active

        fake.down = False
        fake.store.clear()  # token missing, as after a Redis flush

        assert ks.is_active
        assert ks.is_active
        assert not ks.storage_healthy

    def test_another_process_baseline_after_flush_does_not_clear_a_latch(self) -> None:
        """A republished baseline is not a human arm."""
        fake = _FakeRedis()
        runner = KillSwitch(redis_client=self._client(fake))
        api = KillSwitch(redis_client=self._client(fake))

        assert not runner.is_active
        fake.down = True
        assert runner.is_active
        fake.down = False

        fake.store.clear()  # Redis flush: both the trip and the token are gone
        assert not api.is_active  # the API republishes a fresh baseline
        assert fake.store[_ARM_EPOCH_KEY].startswith("baseline:")

        assert runner.is_active  # a new baseline is not a human re-arm
        assert not runner.storage_healthy

        assert api.arm() is True
        assert not runner.is_active

    def test_a_failed_arm_leaves_the_switch_latched(self) -> None:
        fake = _FakeRedis()
        ks = KillSwitch(redis_client=self._client(fake))

        assert not ks.is_active
        baseline = fake.store[_ARM_EPOCH_KEY]

        fake.pipeline_down = True
        assert ks.arm() is False
        assert fake.store[_ARM_EPOCH_KEY] == baseline
        assert ks.is_active
        assert not ks.storage_healthy

        fake.pipeline_down = False
        assert ks.arm() is True
        assert not ks.is_active
        assert ks.storage_healthy

    def test_latch_without_a_baseline_needs_one_more_arm(self) -> None:
        """A process that never read the store stays closed after recovery.

        It records the post-recovery token as its baseline, so a further human
        arm is required.  This is fail-closed and documented.
        """
        fake = _FakeRedis()
        fake.store[_ARM_EPOCH_KEY] = "pre-existing-token"
        fake.down = True
        runner = KillSwitch(redis_client=self._client(fake))
        api = KillSwitch(redis_client=self._client(fake))

        assert runner.is_active  # latches before ever reading a baseline
        fake.down = False

        assert runner.is_active  # records the token, does not clear
        assert runner.is_active

        assert api.arm() is True
        assert not runner.is_active
