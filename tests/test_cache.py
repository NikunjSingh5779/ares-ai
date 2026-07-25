"""Tests for market data cache layer."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from backend.data.cache import MarketDataCache, NullCache
from backend.data.models import OHLCVData


@pytest.fixture
def sample_candle() -> OHLCVData:
    return OHLCVData(
        symbol="BTC-USD",
        source="yahoo",
        interval="1d",
        timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        open=42000.0,
        high=42500.0,
        low=41500.0,
        close=42200.0,
        volume=100.5,
    )


@pytest.fixture
def sample_candles() -> list[OHLCVData]:
    return [
        OHLCVData(
            symbol="BTC-USD",
            source="yahoo",
            interval="1d",
            timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
            open=42000.0,
            high=42500.0,
            low=41500.0,
            close=42200.0,
            volume=100.5,
        ),
        OHLCVData(
            symbol="BTC-USD",
            source="yahoo",
            interval="1d",
            timestamp=datetime(2024, 1, 2, 12, 0, tzinfo=UTC),
            open=42200.0,
            high=43000.0,
            low=41800.0,
            close=42800.0,
            volume=150.75,
        ),
    ]


class TestMarketDataCache:
    def test_cache_unavailable_by_default(self) -> None:
        cache = MarketDataCache()
        assert cache.available is False

    def test_cache_key_format(self) -> None:
        cache = MarketDataCache()
        key = cache._make_key("yahoo", "BTC-USD", "1d")
        assert key.startswith("ares:market_data:yahoo:BTC-USD:1d")

    def test_cache_key_with_timestamp(self) -> None:
        cache = MarketDataCache()
        dt = datetime(2024, 1, 1, tzinfo=UTC)
        key = cache._make_key("yahoo", "BTC-USD", "1d", dt)
        # UTC timestamp for 2024-01-01 00:00:00 = 1704067200
        assert key.endswith(":1704067200")

    def test_range_key(self) -> None:
        cache = MarketDataCache()
        key = cache._range_key("binance", "ETH-USD", "1h")
        assert key == "ares:market_data:binance:ETH-USD:1h"

    def test_ttl_resolution(self) -> None:
        cache = MarketDataCache()
        assert cache._ttl_for("1m") == 30
        assert cache._ttl_for("1h") == 300
        assert cache._ttl_for("1d") == 3600
        assert cache._ttl_for("nonexistent") == 300

    async def test_get_candles_no_redis(self, sample_candles: list[OHLCVData]) -> None:
        cache = MarketDataCache()
        result = await cache.get_candles(source="yahoo", symbol="BTC-USD", interval="1d")
        assert result is None

    async def test_set_candles_no_redis(self, sample_candles: list[OHLCVData]) -> None:
        cache = MarketDataCache()
        count = await cache.set_candles(sample_candles)
        assert count == 0

    async def test_invalidate_no_redis(self) -> None:
        cache = MarketDataCache()
        result = await cache.invalidate("yahoo", "BTC-USD", "1d")
        assert result is False

    async def test_clear_all_no_redis(self) -> None:
        cache = MarketDataCache()
        result = await cache.clear_all()
        assert result is False


class TestNullCache:
    def test_never_available(self) -> None:
        cache = NullCache()
        assert cache.available is False

    async def test_get_returns_none(self) -> None:
        cache = NullCache()
        result = await cache.get_candles(source="yahoo", symbol="BTC-USD", interval="1d")
        assert result is None

    async def test_set_returns_zero(self, sample_candles: list[OHLCVData]) -> None:
        cache = NullCache()
        count = await cache.set_candles(sample_candles)
        assert count == 0

    async def test_invalidate_returns_false(self) -> None:
        cache = NullCache()
        assert await cache.invalidate("yahoo", "BTC-USD", "1d") is False


class TestMarketDataCacheExceptions:
    """Force every except-Exception path in cache.py and assert the log fires."""

    async def test_get_candles_exception_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        """When Redis scan/mget raises, get_candles logs and returns None."""
        mock_redis = AsyncMock(spec=["scan", "mget"])
        mock_redis.scan.side_effect = ConnectionError("Redis connection lost")
        cache = MarketDataCache(redis_client=mock_redis)

        with caplog.at_level(logging.ERROR):
            result = await cache.get_candles("yahoo", "BTC-USD", "1d")

        assert result is None
        assert any("get_candles failed" in rec.message for rec in caplog.records)

    async def test_set_candles_exception_logs(
        self,
        caplog: pytest.LogCaptureFixture,
        sample_candles: list[OHLCVData],
    ) -> None:
        """When Redis pipeline raises, set_candles logs and returns 0."""
        mock_redis = AsyncMock(spec=["pipeline"])
        mock_redis.pipeline.side_effect = ConnectionError("Redis connection lost")
        cache = MarketDataCache(redis_client=mock_redis)

        with caplog.at_level(logging.ERROR):
            result = await cache.set_candles(sample_candles)

        assert result == 0
        assert any("set_candles failed" in rec.message for rec in caplog.records)

    async def test_invalidate_exception_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        """When Redis scan/delete raises, invalidate logs and returns False."""
        mock_redis = AsyncMock(spec=["scan", "delete"])
        mock_redis.scan.side_effect = ConnectionError("Redis connection lost")
        cache = MarketDataCache(redis_client=mock_redis)

        with caplog.at_level(logging.ERROR):
            result = await cache.invalidate("yahoo", "BTC-USD", "1d")

        assert result is False
        assert any("invalidate failed" in rec.message for rec in caplog.records)

    async def test_clear_all_exception_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        """When Redis scan/delete raises, clear_all logs and returns False."""
        mock_redis = AsyncMock(spec=["scan", "delete"])
        mock_redis.scan.side_effect = ConnectionError("Redis connection lost")
        cache = MarketDataCache(redis_client=mock_redis)

        with caplog.at_level(logging.ERROR):
            result = await cache.clear_all()

        assert result is False
        assert any("clear_all failed" in rec.message for rec in caplog.records)
