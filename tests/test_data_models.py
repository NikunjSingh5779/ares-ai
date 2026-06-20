"""Tests for market data models."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.data.models import (
    OHLCVData,
    MarketDataRequest,
    MarketDataResult,
    MarketDataQuery,
    MarketDataSummary,
    Interval,
    Source,
)


class TestOHLCVData:
    def test_valid_ohlcv(self) -> None:
        candle = OHLCVData(
            symbol="BTC-USD",
            source="yahoo",
            interval="1d",
            timestamp=datetime(2024, 1, 1),
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=10000.0,
        )
        assert candle.symbol == "BTC-USD"
        assert candle.open == 100.0

    def test_db_export(self) -> None:
        candle = OHLCVData(
            symbol="BTC-USD",
            source="yahoo",
            interval="1d",
            timestamp=datetime(2024, 1, 1),
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=10000.0,
        )
        db_data = candle.model_dump_for_db()
        assert db_data["symbol"] == "BTC-USD"
        assert db_data["interval"] == "1d"
        assert "open" in db_data
        assert "volume" in db_data

    def test_optional_fields(self) -> None:
        candle = OHLCVData(
            symbol="ETH-USD",
            source="binance",
            interval="1m",
            timestamp=datetime(2024, 1, 1, 12, 0),
            open=1.0,
            high=1.1,
            low=0.9,
            close=1.05,
            volume=0.0,
        )
        assert candle.vwap is None
        assert candle.trades_count is None

    def test_invalid_interval(self) -> None:
        with pytest.raises(ValidationError):
            OHLCVData(
                symbol="BTC-USD",
                source="yahoo",
                interval="2h",  # invalid
                timestamp=datetime(2024, 1, 1),
                open=1, high=2, low=1, close=1.5, volume=0,
            )

    def test_invalid_source(self) -> None:
        with pytest.raises(ValidationError):
            OHLCVData(
                symbol="BTC-USD",
                source="unknown_source",
                interval="1d",
                timestamp=datetime(2024, 1, 1),
                open=1, high=2, low=1, close=1.5, volume=0,
            )


class TestIntervalValidation:
    def test_valid_intervals(self) -> None:
        for interval in Interval.ALL:
            assert Interval.validate(interval) == interval

    def test_invalid_interval(self) -> None:
        with pytest.raises(ValueError, match="Invalid interval"):
            Interval.validate("10m")

    def test_empty_interval(self) -> None:
        with pytest.raises(ValueError):
            Interval.validate("")


class TestSourceValidation:
    def test_valid_sources(self) -> None:
        for source in Source.ALL:
            assert Source.validate(source) == source

    def test_invalid_source(self) -> None:
        with pytest.raises(ValueError, match="Invalid source"):
            Source.validate("alphavantage")


class TestMarketDataRequest:
    def test_defaults(self) -> None:
        req = MarketDataRequest(symbol="BTC-USD")
        assert req.source == "yahoo"
        assert req.interval == "1d"
        assert req.limit == 100

    def test_end_date_default(self) -> None:
        req = MarketDataRequest(symbol="BTC-USD")
        assert req.end_date is not None

    def test_full_params(self) -> None:
        dt = datetime(2024, 1, 1)
        req = MarketDataRequest(
            symbol="ETH-USD",
            source="binance",
            interval="1h",
            start_date=dt,
            end_date=dt,
            limit=500,
        )
        assert req.symbol == "ETH-USD"
        assert req.source == "binance"
        assert req.interval == "1h"
        assert req.limit == 500

    def test_invalid_interval_raises(self) -> None:
        with pytest.raises(ValidationError):
            MarketDataRequest(symbol="BTC-USD", interval="10m")


class TestMarketDataResult:
    def test_defaults(self) -> None:
        result = MarketDataResult(symbol="BTC-USD", source="yahoo", interval="1d")
        assert result.count == 0
        assert result.cached is False
        assert result.errors == []

    def test_with_data(self) -> None:
        result = MarketDataResult(
            symbol="BTC-USD",
            source="yahoo",
            interval="1d",
            count=100,
            cached=True,
            from_cache=100,
        )
        assert result.count == 100
        assert result.from_cache == 100
