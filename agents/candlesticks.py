"""Candlestick pattern detection for market analysis.

Pure functions to evaluate OHLCV data for common candlestick patterns.
"""

from __future__ import annotations

from backend.data.models import OHLCVData


def detect_candlestick_patterns(candles: list[OHLCVData]) -> list[str]:
    """Detect common candlestick patterns from recent OHLCV data.

    Returns a list of detected patterns (e.g., ["Bullish Engulfing", "Doji"]).
    """
    if len(candles) < 2:
        return []

    patterns = []

    # Calculate some basics about the current and previous candles
    current = candles[-1]
    prev = candles[-2]

    # Current candle components
    body_size = abs(current.close - current.open)
    upper_wick = current.high - max(current.open, current.close)
    lower_wick = min(current.open, current.close) - current.low
    total_range = current.high - current.low

    if total_range == 0:
        return patterns

    # Previous candle components
    prev_body_size = abs(prev.close - prev.open)
    prev_is_bullish = prev.close > prev.open
    prev_is_bearish = prev.close < prev.open

    is_bullish = current.close > current.open
    is_bearish = current.close < current.open

    # 1. Doji
    # Body is very small compared to the total range
    if body_size <= total_range * 0.1 and total_range > 0:
        patterns.append("Doji")

    # 2. Hammer / Hanging Man
    # Long lower wick (at least 2x body), small upper wick, small body
    if lower_wick >= 2 * body_size and upper_wick <= 0.1 * total_range and body_size > 0:
        # A true hammer comes after a downtrend, but we'll flag the shape.
        patterns.append("Hammer")

    # 3. Shooting Star / Inverted Hammer
    # Long upper wick (at least 2x body), small lower wick, small body
    if upper_wick >= 2 * body_size and lower_wick <= 0.1 * total_range and body_size > 0:
        patterns.append("Shooting Star")

    # 4. Bullish Engulfing
    # Previous was bearish, current is bullish, and current body engulfs previous body
    if (
        prev_is_bearish
        and is_bullish
        and current.open <= prev.close
        and current.close >= prev.open
        and body_size > prev_body_size
    ):
        patterns.append("Bullish Engulfing")

    # 5. Bearish Engulfing
    # Previous was bullish, current is bearish, and current body engulfs previous body
    if (
        prev_is_bullish
        and is_bearish
        and current.open >= prev.close
        and current.close <= prev.open
        and body_size > prev_body_size
    ):
        patterns.append("Bearish Engulfing")

    return patterns
