"""Tests for the candlesticks module."""

from datetime import UTC, datetime

from agents.candlesticks import detect_candlestick_patterns
from backend.data.models import OHLCVData


def create_candle(open_price: float, high: float, low: float, close: float) -> OHLCVData:
    """Helper to create OHLCVData objects."""
    return OHLCVData(
        symbol="BTC-USD",
        source="yahoo",
        interval="1d",
        timestamp=datetime.now(tz=UTC),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=100.0,
    )


def test_detect_candlestick_patterns_doji():
    """Test detection of a Doji."""
    candles = [
        create_candle(100, 105, 95, 101),
        create_candle(101, 105, 95, 101.1)  # Doji
    ]
    patterns = detect_candlestick_patterns(candles)
    assert "Doji" in patterns


def test_detect_candlestick_patterns_hammer():
    """Test detection of a Hammer."""
    candles = [
        create_candle(100, 105, 95, 101),
        create_candle(100, 102, 80, 101)  # Hammer (long lower wick)
    ]
    patterns = detect_candlestick_patterns(candles)
    assert "Hammer" in patterns


def test_detect_candlestick_patterns_shooting_star():
    """Test detection of a Shooting Star."""
    candles = [
        create_candle(100, 105, 95, 101),
        create_candle(100, 120, 99, 101)  # Shooting Star (long upper wick)
    ]
    patterns = detect_candlestick_patterns(candles)
    assert "Shooting Star" in patterns


def test_detect_candlestick_patterns_bullish_engulfing():
    """Test detection of Bullish Engulfing."""
    candles = [
        create_candle(105, 110, 95, 100),  # Bearish
        create_candle(99, 115, 90, 106)   # Bullish and engulfs
    ]
    patterns = detect_candlestick_patterns(candles)
    assert "Bullish Engulfing" in patterns


def test_detect_candlestick_patterns_bearish_engulfing():
    """Test detection of Bearish Engulfing."""
    candles = [
        create_candle(95, 110, 90, 100),   # Bullish
        create_candle(101, 110, 85, 94)    # Bearish and engulfs
    ]
    patterns = detect_candlestick_patterns(candles)
    assert "Bearish Engulfing" in patterns


def test_detect_candlestick_patterns_no_data():
    """Test with insufficient data."""
    assert detect_candlestick_patterns([]) == []
    assert detect_candlestick_patterns([create_candle(100, 105, 95, 101)]) == []
