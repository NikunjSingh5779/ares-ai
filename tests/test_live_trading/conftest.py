import pytest
import redis

from configs.settings import settings


@pytest.fixture(autouse=True)
def clear_kill_switch_redis():
    try:
        r = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            db=settings.redis_db,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        r.delete("ares:kill_switch:active", "ares:kill_switch:reason", "ares:kill_switch:timestamp", "ares:mode")
    except (redis.ConnectionError, redis.TimeoutError, OSError):
        # Redis not available locally — skip cleanup silently.
        # Tests that genuinely need Redis will fail on their own merit.
        pass
