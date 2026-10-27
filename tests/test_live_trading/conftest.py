import pytest


@pytest.fixture(autouse=True)
def _enable_live_trading_for_engine_tests(monkeypatch):
    """Engine unit tests exercise live mechanics, not the paper-only default.

    The paper-only gate itself is covered by test_engine_paper_only.py and
    the route tests that explicitly disable it.
    """
    from configs.settings import settings

    monkeypatch.setattr(settings, "live_trading_enabled", True)


@pytest.fixture
def clear_kill_switch_redis():
    """Clear Redis-backed kill switch state between tests.

    Explicitly request this fixture in any test that exercises
    Redis-persisted kill switch state (e.g. integration tests for
    :func:`~live_trading.safety.KillSwitch`).
    """
    try:
        import redis

        from configs.settings import settings

        r = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            db=settings.redis_db,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        r.delete(
            "ares:kill_switch:active",
            "ares:kill_switch:reason",
            "ares:kill_switch:timestamp",
            "ares:kill_switch:arm_epoch",
            "ares:mode",
        )
    except (redis.ConnectionError, redis.TimeoutError, OSError):
        # Redis not available locally — skip cleanup silently.
        # Tests that genuinely need Redis will fail on their own merit.
        pass
