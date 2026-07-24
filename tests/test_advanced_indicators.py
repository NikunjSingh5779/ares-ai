"""Tests for advanced technical indicators and time series metrics."""

from __future__ import annotations

from datetime import datetime

from agents.indicators import (
    compute_adx,
    compute_stochastic,
    compute_time_series_metrics,
)
from backend.data.models import OHLCVData


def _make_candles(prices: list[float], highs: list[float] | None = None, lows: list[float] | None = None) -> list[OHLCVData]:
    candles = []
    for i, p in enumerate(prices):
        h = highs[i] if highs else p * 1.05
        low_val = lows[i] if lows else p * 0.95
        candles.append(
            OHLCVData(
                symbol="TEST",
                source="yahoo",
                interval="1d",
                timestamp=datetime(2024, 1, (i % 28) + 1),
                open=p,
                high=h,
                low=low_val,
                close=p,
                volume=1000.0,
            )
        )
    return candles


class TestStochastic:
    def test_stochastic_insufficient_data(self):
        prices = [100.0] * 10
        candles = _make_candles(prices)
        result = compute_stochastic(candles, period=14, smooth_k=3, smooth_d=3)
        assert result["k"] is None
        assert result["d"] is None

    def test_stochastic_constant_price(self):
        prices = [100.0] * 20
        highs = [105.0] * 20
        lows = [95.0] * 20
        candles = _make_candles(prices, highs, lows)
        result = compute_stochastic(candles, period=14, smooth_k=3, smooth_d=3)
        # Price is exactly at the middle of high-low range, stochastic K should be 50
        assert result["k"] is not None
        assert result["d"] is not None
        assert 49.0 <= result["k"] <= 51.0


class TestADX:
    def test_adx_insufficient_data(self):
        prices = [100.0] * 25
        candles = _make_candles(prices)
        result = compute_adx(candles, period=14)
        assert result is None

    def test_adx_trending_data(self):
        prices = [100.0 + i for i in range(50)]
        highs = [p * 1.02 for p in prices]
        lows = [p * 0.98 for p in prices]
        candles = _make_candles(prices, highs, lows)
        result = compute_adx(candles, period=14)
        assert result is not None
        assert result > 0


class TestTimeSeriesMetrics:
    def test_time_series_insufficient_data(self):
        prices = [100.0] * 20  # needs at least 30
        candles = _make_candles(prices)
        result = compute_time_series_metrics(candles)
        assert result["stationarity"] in ("unknown", "non-stationary", "stationary")
        assert result["seasonal_strength"] is None

    def test_time_series_constant(self):
        prices = [100.0] * 100
        candles = _make_candles(prices)
        result = compute_time_series_metrics(candles)
        # Constant data cannot be decomposed easily, might be stationary or throw warning
        assert "stationarity" in result

    def test_time_series_trending(self):
        prices = [100.0 + i for i in range(100)]
        candles = _make_candles(prices)
        result = compute_time_series_metrics(candles)
        # Clearly non-stationary
        assert result["stationarity"] == "non-stationary"
        assert result["trend_strength"] is not None
