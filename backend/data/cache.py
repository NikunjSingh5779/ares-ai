"""Redis cache layer for market data."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from backend.data.models import OHLCVData

# Cache key pattern components
KEY_PREFIX = "ares:market_data"
KEY_SEPARATOR = ":"

# Cache TTLs by interval (seconds)
INTERVAL_TTL: dict[str, int] = {
    "1m": 30,
    "5m": 60,
    "15m": 120,
    "30m": 180,
    "1h": 300,
    "4h": 600,
    "1d": 3600,
    "1w": 7200,
    "1mo": 14400,
}

DEFAULT_TTL = 300  # 5 minutes


class MarketDataCache:
    """Redis-backed cache for market data.

    Cache-aside pattern:
    1. Check cache on read
    2. On miss, fetch from source, store in cache, return
    3. Cache TTL varies by interval (shorter for real-time data)

    Gracefully degrades: if Redis is unavailable, cache operations
    return None / no-op rather than raising.
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        """Initialize cache.

        Args:
            redis_client: Redis async client. If None, cache is a no-op.
        """
        self._redis = redis_client

    @property
    def available(self) -> bool:
        """Check if Redis is configured and available."""
        return self._redis is not None

    def _make_key(
        self,
        source: str,
        symbol: str,
        interval: str,
        timestamp: datetime | None = None,
    ) -> str:
        """Build a cache key for market data."""
        parts = [KEY_PREFIX, source, symbol, interval]
        if timestamp:
            parts.append(str(int(timestamp.timestamp())))
        return KEY_SEPARATOR.join(parts)

    def _range_key(self, source: str, symbol: str, interval: str) -> str:
        """Build a key prefix for range queries."""
        return f"{KEY_PREFIX}{KEY_SEPARATOR}{source}{KEY_SEPARATOR}{symbol}{KEY_SEPARATOR}{interval}"

    def _ttl_for(self, interval: str) -> int:
        """Get TTL in seconds for a given interval."""
        return INTERVAL_TTL.get(interval, DEFAULT_TTL)

    async def get_candles(
        self,
        source: str,
        symbol: str,
        interval: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[OHLCVData] | None:
        """Get cached candles for a range.

        Returns None if cache is unavailable, data not found, or
        the range exceeds what's cached.
        """
        if not self.available:
            return None

        try:
            pattern = self._range_key(source, symbol, interval) + KEY_SEPARATOR + "*"
            cursor, keys = await self._redis.scan(match=pattern, count=500)

            if not keys:
                return None

            raw_values = await self._redis.mget(*keys)
            candles: list[OHLCVData] = []

            for raw in raw_values:
                if raw is None:
                    continue
                try:
                    data = json.loads(raw)
                    ts = datetime.fromisoformat(data["timestamp"])
                    if start_date and ts < start_date:
                        continue
                    if end_date and ts > end_date:
                        continue
                    candles.append(OHLCVData(**data))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue

            if not candles:
                return None

            candles.sort(key=lambda c: c.timestamp)
            return candles

        except Exception:
            return None

    async def set_candles(
        self,
        candles: list[OHLCVData],
    ) -> int:
        """Store candles in cache.

        Returns number of candles cached, or 0 if cache unavailable.
        """
        if not self.available or not candles:
            return 0

        ttl = self._ttl_for(candles[0].interval)
        count = 0

        try:
            async with self._redis.pipeline(transaction=False) as pipe:
                for candle in candles:
                    key = self._make_key(
                        candle.source, candle.symbol, candle.interval, candle.timestamp
                    )
                    pipe.setex(key, ttl, candle.model_dump_json())
                await pipe.execute()
            return len(candles)
        except Exception:
            return 0

    async def invalidate(
        self,
        source: str,
        symbol: str,
        interval: str,
    ) -> bool:
        """Invalidate all cached entries for a source/symbol/interval combo."""
        if not self.available:
            return False

        try:
            pattern = self._range_key(source, symbol, interval) + KEY_SEPARATOR + "*"
            cursor, keys = await self._redis.scan(match=pattern, count=500)
            if keys:
                await self._redis.delete(*keys)
            return True
        except Exception:
            return False

    async def clear_all(self) -> bool:
        """Clear all market data from cache."""
        if not self.available:
            return False

        try:
            pattern = f"{KEY_PREFIX}{KEY_SEPARATOR}*"
            cursor, keys = await self._redis.scan(match=pattern, count=1000)
            if keys:
                await self._redis.delete(*keys)
            return True
        except Exception:
            return False


class NullCache(MarketDataCache):
    """No-op cache for when Redis is unavailable.

    All methods return None / 0 / False without raising.
    Use this as a safe default when no Redis client is configured.
    """

    def __init__(self) -> None:
        super().__init__(redis_client=None)

    @property
    def available(self) -> bool:
        return False
