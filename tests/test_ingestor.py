"""Tests for market data ingestor."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from backend.data.cache import NullCache
from backend.data.ingestor import MarketDataIngestor
from backend.data.models import MarketDataRequest
from backend.data.repository import MarketDataRepository
from backend.data.sources.registry import SourceRegistry
from backend.data.sources.yahoo import YahooFinanceSource


class TestMarketDataIngestor:
    @pytest.fixture
    def mock_yahoo(self) -> YahooFinanceSource:
        source = YahooFinanceSource()
        source.fetch_ohlcv = AsyncMock(return_value=[])  # type: ignore[method-assign]
        return source

    @pytest.fixture
    def registry(self, mock_yahoo: YahooFinanceSource) -> SourceRegistry:
        reg = SourceRegistry()
        reg.register(mock_yahoo)
        return reg

    @pytest.fixture
    def ingestor(self, registry: SourceRegistry) -> MarketDataIngestor:
        return MarketDataIngestor(
            source_registry=registry,
            cache=NullCache(),
            repository=MarketDataRepository(),
        )

    async def test_ingest_empty_result(self, ingestor: MarketDataIngestor) -> None:
        request = MarketDataRequest(symbol="BTC-USD", source="yahoo", interval="1d", limit=10)
        result = await ingestor.ingest(request)

        assert result.symbol == "BTC-USD"
        assert result.source == "yahoo"
        assert result.count == 0
        assert result.cached is False
        assert result.from_cache == 0
        assert result.from_source == 0
        assert result.stored == 0
        assert result.errors == []

    async def test_ingest_with_data(self, registry: SourceRegistry) -> None:
        """Test ingestor with data returned from source."""
        from backend.data.models import OHLCVData

        source = registry.get("yahoo")
        candle = OHLCVData(
            symbol="BTC-USD", source="yahoo", interval="1d",
            timestamp=datetime(2024, 1, 1),
            open=42000, high=42500, low=41500, close=42200, volume=100,
        )
        source.fetch_ohlcv = AsyncMock(return_value=[candle])  # type: ignore[method-assign]

        # Mock repository
        mock_repo = MarketDataRepository()
        mock_repo.insert_ohlcv = AsyncMock(return_value=1)  # type: ignore[method-assign]

        ingestor = MarketDataIngestor(
            source_registry=registry,
            cache=NullCache(),
            repository=mock_repo,
        )

        request = MarketDataRequest(symbol="BTC-USD", source="yahoo", interval="1d")
        result = await ingestor.ingest(request)

        assert result.count == 1
        assert result.from_source == 1
        assert result.stored == 1
        assert result.cached is False

    async def test_ingest_source_error(self, ingestor: MarketDataIngestor) -> None:
        """Test ingestor handles source exceptions gracefully."""
        ingestor.sources.get("yahoo").fetch_ohlcv = AsyncMock(  # type: ignore[method-assign]
            side_effect=ConnectionError("API unavailable")
        )

        request = MarketDataRequest(symbol="BTC-USD", source="yahoo", interval="1d")
        result = await ingestor.ingest(request)

        assert result.count == 0
        assert len(result.errors) == 1
        assert "API unavailable" in result.errors[0]

    async def test_ingest_batch(self, registry: SourceRegistry) -> None:
        """Test batch ingestion."""
        source = registry.get("yahoo")
        source.fetch_ohlcv = AsyncMock(return_value=[])  # type: ignore[method-assign]

        ingestor = MarketDataIngestor(
            source_registry=registry,
            cache=NullCache(),
        )

        results = await ingestor.ingest_batch(
            symbols=["BTC-USD", "ETH-USD"],
            source="yahoo",
            interval="1d",
            limit=10,
        )

        assert len(results) == 2
        assert results[0].symbol == "BTC-USD"
        assert results[1].symbol == "ETH-USD"

    async def test_refresh(self, registry: SourceRegistry) -> None:
        """Test force-refresh invalidates cache then fetches."""
        from backend.data.models import OHLCVData

        source = registry.get("yahoo")
        source.fetch_ohlcv = AsyncMock(return_value=[])  # type: ignore[method-assign]

        ingestor = MarketDataIngestor(
            source_registry=registry,
            cache=NullCache(),
        )

        result = await ingestor.refresh("BTC-USD", source="yahoo", interval="1d")
        assert result.symbol == "BTC-USD"

    def test_stats(self, ingestor: MarketDataIngestor) -> None:
        stats = ingestor.get_stats()
        assert "total_requests" in stats
        assert "cache_hits" in stats
        assert "cache_misses" in stats
        assert "errors" in stats
        assert stats["total_requests"] == 0

    async def test_stats_tracked(self, ingestor: MarketDataIngestor) -> None:
        """Verify stats increment on requests."""
        request = MarketDataRequest(symbol="BTC-USD", source="yahoo", interval="1d")
        await ingestor.ingest(request)

        stats = ingestor.get_stats()
        assert stats["total_requests"] == 1
        assert stats["cache_misses"] == 1  # NullCache always misses
