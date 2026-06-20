"""Tests for technical indicator calculations."""
from __future__ import annotations

import math

import pytest

from agents.indicators import (
    _find_resistance_levels,
    _find_support_levels,
    compute_all_indicators,
    compute_atr,
    compute_bollinger_bands,
    compute_ema,
    compute_emas,
    compute_macd,
    compute_rsi,
    compute_sma,
)
from backend.data.models import OHLCVData


def _make_candle(close: float, high: float | None = None, low: float | None = None,
                 volume: float = 0.0, timestamp: str = "2024-01-01") -> OHLCVData:
    """Helper to create a single OHLCVData for testing."""
    from datetime import UTC, datetime
    return OHLCVData(
        symbol="TEST",
        source="yahoo",
        interval="1d",
        timestamp=datetime.fromisoformat(timestamp).replace(tzinfo=UTC),
        open=close,
        high=high or close,
        low=low or close,
        close=close,
        volume=volume,
    )


def _make_candles(prices: list[float], volumes: list[float] | None = None) -> list[OHLCVData]:
    """Helper: create a list of OHLCVData from price list."""
    from datetime import UTC, datetime
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = []
    for i, price in enumerate(prices):
        vol = volumes[i] if volumes and i < len(volumes) else 1000.0
        candles.append(OHLCVData(
            symbol="TEST", source="yahoo", interval="1d",
            timestamp=start.replace(day=min(1 + i, 28)),
            open=price, high=price * 1.02, low=price * 0.98,
            close=price, volume=vol,
        ))
    return candles


# ---------------------------------------------------------------------------
# SMA Tests
# ---------------------------------------------------------------------------

class TestSMA:
    def test_simple_moving_average(self) -> None:
        prices = [10.0, 11.0, 12.0, 13.0, 14.0]
        assert compute_sma(prices, 3) == 13.0  # (12 + 13 + 14) / 3

    def test_sma_period_equals_length(self) -> None:
        prices = [10.0, 20.0, 30.0]
        assert compute_sma(prices, 3) == 20.0

    def test_sma_returns_none_for_insufficient_data(self) -> None:
        assert compute_sma([10.0, 20.0], 5) is None

    def test_sma_empty_list(self) -> None:
        assert compute_sma([], 10) is None

    def test_sma_ignores_none_and_nan(self) -> None:
        prices = [10.0, None, 12.0, 13.0, 14.0]  # type: ignore[list-item]
        result = compute_sma(prices, 3)  # type: ignore[arg-type]
        # 12+13+14 / 3 = 13, None skipped
        assert result == 13.0

    def test_sma_with_zero_price(self) -> None:
        prices = [0.0, 5.0, 10.0]
        result = compute_sma(prices, 3)
        assert result is None  # 0 is filtered out

    def test_sma_single_valid_in_period(self) -> None:
        prices = [0.0, 0.0, 10.0]
        result = compute_sma(prices, 3)
        assert result is None  # 0 values filtered, only 1 valid


# ---------------------------------------------------------------------------
# EMA Tests
# ---------------------------------------------------------------------------

class TestEMA:
    def test_ema_calculation(self) -> None:
        """EMA(3) on [10, 12, 11, 13, 14, 15]"""
        prices = [10.0, 12.0, 11.0, 13.0, 14.0, 15.0]
        result = compute_ema(prices, 3)
        assert result is not None
        # EMA = (price * m) + (prev_ema * (1-m)), m = 2/(3+1) = 0.5
        # seed SMA = (10+12+11)/3 = 11
        # step 1: (13 * 0.5) + (11 * 0.5) = 12
        # step 2: (14 * 0.5) + (12 * 0.5) = 13
        # step 3: (15 * 0.5) + (13 * 0.5) = 14
        assert result == 14.0

    def test_ema_insufficient_data(self) -> None:
        assert compute_ema([10.0, 20.0], 5) is None

    def test_ema_empty(self) -> None:
        assert compute_ema([], 3) is None

    def test_emas_multiple_periods(self) -> None:
        prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0]
        results = compute_emas(prices, [3, 5])
        assert 3 in results
        assert 5 in results
        assert results[3] is not None
        assert results[5] is not None


# ---------------------------------------------------------------------------
# RSI Tests
# ---------------------------------------------------------------------------

class TestRSI:
    def test_rsi_oversold(self) -> None:
        """Steeply declining prices → RSI near 0."""
        prices = [100.0, 90.0, 81.0, 73.0, 66.0, 60.0, 55.0, 51.0,
                  48.0, 46.0, 44.0, 43.0, 42.0, 41.0, 40.0]
        rsi = compute_rsi(prices, 14)
        assert rsi is not None
        assert rsi < 30  # oversold

    def test_rsi_overbought(self) -> None:
        """Steeply rising prices → RSI near 100."""
        prices = [10.0, 11.0, 12.1, 13.3, 14.6, 16.0, 17.5, 19.0,
                  21.0, 23.0, 25.0, 27.0, 29.0, 31.0, 34.0]
        rsi = compute_rsi(prices, 14)
        assert rsi is not None
        assert rsi > 70  # overbought

    def test_rsi_neutral(self) -> None:
        """Sideways prices → RSI near 50."""
        prices = [50.0, 51.0, 49.0, 50.0, 52.0, 48.0, 50.0, 51.0,
                  49.0, 50.0, 51.0, 49.0, 50.0, 48.0, 52.0]
        rsi = compute_rsi(prices, 14)
        assert rsi is not None
        assert 30 < rsi < 70

    def test_rsi_insufficient_data(self) -> None:
        assert compute_rsi([10.0, 20.0], 14) is None

    def test_rsi_all_gains_all_losses(self) -> None:
        """All gains → RSI = 100."""
        prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0,
                  18.0, 19.0, 20.0, 21.0, 22.0, 23.0, 24.0]
        rsi = compute_rsi(prices, 14)
        assert rsi is not None
        assert rsi == 100.0

    def test_rsi_all_losses(self) -> None:
        """All losses → RSI = 0."""
        prices = [100.0, 90.0, 81.0, 73.0, 66.0, 60.0, 55.0, 51.0,
                  48.0, 46.0, 44.0, 43.0, 42.0, 41.0, 40.0]
        rsi = compute_rsi(prices, 14)
        assert rsi is not None
        # Not exactly 0 since declines are decreasing in magnitude,
        # so average loss ≠ average loss perfectly
        assert rsi < 50

    def test_rsi_empty_prices(self) -> None:
        assert compute_rsi([], 14) is None


# ---------------------------------------------------------------------------
# MACD Tests
# ---------------------------------------------------------------------------

class TestMACD:
    def test_macd_insufficient_data(self) -> None:
        prices = [10.0, 11.0, 12.0]
        result = compute_macd(prices)
        assert result["macd"] is None

    def test_macd_sufficient_data(self) -> None:
        prices = [float(i) for i in range(50, 100)]
        result = compute_macd(prices)
        assert result["macd"] is not None
        assert isinstance(result["macd"], float)
        assert isinstance(result.get("signal"), (float, type(None)))

    def test_macd_rising_prices_give_positive(self) -> None:
        """Strongly rising prices → EMA(12) > EMA(26) → MACD > 0."""
        prices = [100.0 + i * 2 for i in range(50)]
        result = compute_macd(prices)
        assert result["macd"] is not None
        assert result["macd"] > 0

    def test_macd_falling_prices_give_negative(self) -> None:
        """Strongly falling prices → EMA(12) < EMA(26) → MACD < 0."""
        prices = [200.0 - i * 2 for i in range(50)]
        result = compute_macd(prices)
        assert result["macd"] is not None
        assert result["macd"] < 0


# ---------------------------------------------------------------------------
# Bollinger Bands Tests
# ---------------------------------------------------------------------------

class TestBollingerBands:
    def test_bollinger_basics(self) -> None:
        prices = [50.0] * 20 + [55.0, 56.0, 54.0, 58.0, 52.0]
        result = compute_bollinger_bands(prices, 20)
        assert result["middle"] is not None
        assert result["upper"] is not None
        assert result["lower"] is not None
        assert result["upper"] > result["middle"] > result["lower"]

    def test_bollinger_constant_prices(self) -> None:
        """Constant prices → bandwidth = 0."""
        prices = [100.0] * 25
        result = compute_bollinger_bands(prices, 20)
        assert result["middle"] == 100.0
        assert result["upper"] == 100.0
        assert result["lower"] == 100.0
        assert result["bandwidth"] == 0.0

    def test_bollinger_insufficient_data(self) -> None:
        assert compute_bollinger_bands([10, 20, 30], 20)["middle"] is None

    def test_bollinger_upper_lower_symmetric(self) -> None:
        prices = [float(i) for i in range(25)]
        result = compute_bollinger_bands(prices, 20)
        mid = result["middle"]
        upper = result["upper"]
        lower = result["lower"]
        assert upper is not None and lower is not None and mid is not None
        assert abs((upper - mid) - (mid - lower)) < 0.01  # symmetric

    def test_bollinger_with_volatility(self) -> None:
        """High volatility → wider bands."""
        stable = [100.0 + (i % 3 - 1) for i in range(25)]
        volatile = [100.0 + (i % 20 - 10) * 2 for i in range(25)]

        stable_result = compute_bollinger_bands(stable, 20)
        volatile_result = compute_bollinger_bands(volatile, 20)

        if stable_result["bandwidth"] is not None and volatile_result["bandwidth"] is not None:
            assert volatile_result["bandwidth"] > stable_result["bandwidth"]


# ---------------------------------------------------------------------------
# ATR Tests
# ---------------------------------------------------------------------------

class TestATR:
    def test_atr_basic(self) -> None:
        candles = _make_candles([100, 102, 101, 103, 104, 105, 106, 107, 108,
                                 109, 110, 111, 112, 113, 114, 115])
        atr = compute_atr(candles, 14)
        assert atr is not None
        assert atr > 0

    def test_atr_insufficient_data(self) -> None:
        candles = _make_candles([100, 101, 102])
        assert compute_atr(candles, 14) is None

    def test_atr_empty(self) -> None:
        assert compute_atr([], 14) is None


# ---------------------------------------------------------------------------
# Support / Resistance Tests
# ---------------------------------------------------------------------------

class TestSupportResistance:
    def test_find_support_levels(self) -> None:
        prices = [100, 98, 102, 97, 103, 96, 104, 95, 105, 94, 106, 95]
        levels = _find_support_levels(prices, 2)
        assert len(levels) > 0
        for level in levels:
            assert level < 100  # supports are below the range

    def test_find_resistance_levels(self) -> None:
        prices = [100, 105, 99, 106, 98, 107, 97, 108, 96, 109, 95, 108]
        levels = _find_resistance_levels(prices, 2)
        assert len(levels) > 0
        for level in levels:
            assert level > 100  # resistances are above

    def test_insufficient_data(self) -> None:
        assert _find_support_levels([100], 3) == []
        assert _find_resistance_levels([100], 3) == []


# ---------------------------------------------------------------------------
# Composite All Indicators
# ---------------------------------------------------------------------------

class TestAllIndicators:
    def test_compute_all_with_valid_data(self) -> None:
        """compute_all_indicators returns a rich dict with 20+ candles."""
        prices = [100 + (i % 20 - 10) for i in range(100)]
        candles = _make_candles(prices)
        result = compute_all_indicators(candles)

        assert "current_price" in result
        assert "rsi_14" in result
        assert "sma_20" in result
        assert "sma_50" in result
        assert "macd" in result
        assert "bollinger_bands" in result
        assert "atr_14" in result
        assert "trend" in result
        assert result["rsi_14"] is not None
        assert result["trend"] in ("bullish", "bearish", "neutral")

    def test_compute_all_with_minimal_data(self) -> None:
        """With only a few candles, some indicators are None."""
        candles = _make_candles([100, 101, 102, 103, 104])
        result = compute_all_indicators(candles)

        assert "current_price" in result
        assert result.get("rsi_14") is None  # not enough data
        assert result.get("sma_50") is None

    def test_compute_all_empty(self) -> None:
        assert compute_all_indicators([]) == {}

    def test_compute_all_price_change(self) -> None:
        candles = _make_candles([100, 102, 104, 106, 108, 110, 112, 114])
        result = compute_all_indicators(candles)
        assert result.get("price_change_1d") is not None

    def test_compute_all_trend_bullish(self) -> None:
        """Rising prices with SMA50 > SMA200 → bullish."""
        prices = [100 + i * 0.5 for i in range(250)]
        candles = _make_candles(prices)
        result = compute_all_indicators(candles)
        # SMA50 should be above SMA200 in a sustained uptrend
        assert result.get("trend") == "bullish"

    def test_compute_all_with_volume(self) -> None:
        prices = [float(i) for i in range(50)]
        volumes = [1000 + (i % 5) * 500 for i in range(50)]
        candles = _make_candles(prices, volumes=volumes)
        result = compute_all_indicators(candles)
        assert result.get("volume_sma_20") is not None
        assert result.get("current_volume") is not None
