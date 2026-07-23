import pytest
import redis

from configs.settings import settings


@pytest.fixture
def clear_kill_switch_redis():
    """Clear Redis-backed kill switch state between tests.

    Only used by tests that exercise Redis-persisted kill switch state.
    Does not auto-apply — tests must explicitly request this fixture.
    """
    r = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password or None,
        db=settings.redis_db,
        decode_responses=True
    )
    r.delete('ares:kill_switch:active', 'ares:kill_switch:reason', 'ares:kill_switch:timestamp', 'ares:mode')
