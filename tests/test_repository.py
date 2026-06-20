"""Tests for market data repository."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.data.models import OHLCVData
from backend.data.repository import MarketDataRepository


@pytest.fixture
def sample_candles() -> list[OHLCVData]:
    return [
        OHLCVData(
            symbol="BTC-USD",
            source="yahoo",
            interval="1d",
            timestamp=datetime(2024, 1, 1, tzinfo=UTC),
            open=42000.0, high=42500.0, low=41500.0, close=42200.0, volume=100.0,
        ),
        OHLCVData(
            symbol="BTC-USD",
            source="yahoo",
            interval="1d",
            timestamp=datetime(2024, 1, 2, tzinfo=UTC),
            open=42200.0, high=43000.0, low=41800.0, close=42800.0, volume=150.0,
        ),
    ]


class TestMarketDataRepository:
    def test_repo_initialized(self) -> None:
        repo = MarketDataRepository()
        assert repo._session_factory is None

    async def test_insert_requires_session_factory(self, sample_candles: list[OHLCVData]) -> None:
        repo = MarketDataRepository()
        with pytest.raises(RuntimeError, match="No session factory configured"):
            await repo.insert_ohlcv(sample_candles)

    async def test_insert_with_session(self, sample_candles: list[OHLCVData]) -> None:
        """Test insert_ohlcv with explicit session."""
        repo = MarketDataRepository()
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()

        count = await repo._do_insert(mock_session, sample_candles)
        assert count == 2
        mock_session.execute.assert_awaited_once()

    async def test_insert_validates_intervals(self) -> None:
        repo = MarketDataRepository()
        mock_session = AsyncMock()
        # Pydantic model validates at construction, so bypass with model_construct
        bad_candle = OHLCVData.model_construct(
            symbol="BTC-USD", source="yahoo", interval="10m",
            timestamp=datetime(2024, 1, 1, tzinfo=UTC),
            open=1, high=2, low=1, close=1.5, volume=0,
        )

        with pytest.raises(AssertionError, match="Invalid interval"):
            await repo._do_insert(mock_session, [bad_candle])

    async def test_insert_validates_sources(self) -> None:
        repo = MarketDataRepository()
        mock_session = AsyncMock()
        bad_candle = OHLCVData.model_construct(
            symbol="BTC-USD", source="unknown_source", interval="1d",
            timestamp=datetime(2024, 1, 1, tzinfo=UTC),
            open=1, high=2, low=1, close=1.5, volume=0,
        )

        with pytest.raises(AssertionError, match="Invalid source"):
            await repo._do_insert(mock_session, [bad_candle])

    async def test_query_with_session(self) -> None:
        """Test query with explicit session returns results."""
        repo = MarketDataRepository()
        mock_session = AsyncMock()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("BTC-USD", "yahoo", "1d", datetime(2024, 1, 1, tzinfo=UTC),
             42000.0, 42500.0, 41500.0, 42200.0, 100.0, None, None),
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)

        candles = await repo._do_query(
            mock_session,
            symbol="BTC-USD",
            interval="1d",
            source=None,
            start_date=None,
            end_date=None,
            limit=10,
            offset=0,
            order="desc",
        )

        assert len(candles) == 1
        assert candles[0].symbol == "BTC-USD"
        assert candles[0].close == 42200.0
        assert candles[0].vwap is None

    async def test_summary_no_session(self) -> None:
        repo = MarketDataRepository()
        result = await repo.get_summary("BTC-USD", "1d")
        assert result is None

    async def test_check_exists_no_session(self) -> None:
        repo = MarketDataRepository()
        result = await repo.check_data_exists("BTC-USD", "yahoo", "1d")
        assert result is False
