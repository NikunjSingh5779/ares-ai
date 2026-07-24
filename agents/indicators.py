"""Technical indicator calculations for market analysis.

All functions are pure — they take numeric arrays and return computed values.
Handles edge cases: insufficient data, zero division, NaN propagation.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from agents.candlesticks import detect_candlestick_patterns
from backend.data.models import OHLCVData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_prices(prices: list[float], min_periods: int = 2) -> list[float]:
    """Validate and clean price data. Returns list guaranteed to have min_periods."""
    cleaned = [p for p in prices if p is not None and p > 0 and not (isinstance(p, float) and math.isnan(p))]
    if len(cleaned) < min_periods:
        return []
    return cleaned


def _extract_closes(candles: list[OHLCVData]) -> list[float]:
    """Extract close prices from OHLCV candles, most recent last."""
    return [c.close for c in candles]


def _extract_highs(candles: list[OHLCVData]) -> list[float]:
    return [c.high for c in candles]


def _extract_lows(candles: list[OHLCVData]) -> list[float]:
    return [c.low for c in candles]


def _extract_volumes(candles: list[OHLCVData]) -> list[float]:
    return [c.volume for c in candles]


# ---------------------------------------------------------------------------
# Moving Averages
# ---------------------------------------------------------------------------


def compute_sma(prices: list[float], period: int = 20) -> float | None:
    """Simple Moving Average."""
    validated = _validate_prices(prices, min_periods=period)
    if not validated or len(validated) < period:
        return None
    recent = validated[-period:]
    return sum(recent) / period


def compute_ema(prices: list[float], period: int = 20) -> float | None:
    """Exponential Moving Average.

    EMA = (Price × multiplier) + (previous_EMA × (1 - multiplier))
    multiplier = 2 / (period + 1)
    First EMA is SMA of first `period` values.
    """
    validated = _validate_prices(prices, min_periods=period + 1)
    if not validated or len(validated) < period + 1:
        return None

    multiplier = 2.0 / (period + 1)
    ema = sum(validated[:period]) / period  # SMA seed

    for price in validated[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


def compute_emas(prices: list[float], periods: list[int]) -> dict[int, float | None]:
    """Compute EMAs for multiple periods efficiently."""
    return {p: compute_ema(prices, p) for p in periods}


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------


def compute_rsi(prices: list[float], period: int = 14) -> float | None:
    """Relative Strength Index.

    RSI = 100 - (100 / (1 + RS))
    RS = average gain / average loss over `period` periods

    Returns value between 0-100, or None if insufficient data.
    """
    validated = _validate_prices(prices, min_periods=period + 1)
    if not validated or len(validated) < period + 1:
        return None

    # Calculate price changes
    changes = [validated[i] - validated[i - 1] for i in range(1, len(validated))]

    if len(changes) < period:
        return None

    # Use only the last `period` changes for primary calculation
    recent_changes = changes[-period:]

    gains = [max(c, 0) for c in recent_changes]
    losses = [max(-c, 0) for c in recent_changes]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 2)


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


def compute_macd(prices: list[float]) -> dict[str, float | None]:
    """MACD (Moving Average Convergence Divergence).

    Returns:
        {"macd": MACD line, "signal": signal line, "histogram": MACD - signal}
    """
    ema_12 = compute_ema(prices, 12)
    ema_26 = compute_ema(prices, 26)

    if ema_12 is None or ema_26 is None:
        return {"macd": None, "signal": None, "histogram": None}

    macd_value = round(ema_12 - ema_26, 4)

    # For signal line, we need the full MACD series, which requires
    # enough data. If we don't have enough, return just the MACD line.
    if len(prices) < 35:  # 26 + 9
        return {"macd": macd_value, "signal": None, "histogram": None}

    # Compute full MACD series for signal line
    macd_series = _compute_macd_series(prices)
    if len(macd_series) >= 9:
        signal_val = compute_ema(macd_series, 9)
        if signal_val is not None:
            signal_rounded = round(signal_val, 4)
            return {
                "macd": macd_value,
                "signal": signal_rounded,
                "histogram": round(macd_value - signal_rounded, 4),
            }

    return {"macd": macd_value, "signal": None, "histogram": None}


def _get_macd_series(prices: list[float]) -> list[float]:
    """Placeholder — not used directly."""
    return []


def _compute_macd_series(prices: list[float]) -> list[float]:
    """Compute the full MACD line series."""
    if len(prices) < 27:
        return []

    result = []
    for i in range(26, len(prices)):
        segment = prices[: i + 1]
        ema_12 = compute_ema(segment, 12)
        ema_26 = compute_ema(segment, 26)
        if ema_12 is not None and ema_26 is not None:
            result.append(ema_12 - ema_26)
    return result


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------


def compute_bollinger_bands(
    prices: list[float],
    period: int = 20,
    std_multiplier: float = 2.0,
) -> dict[str, float | None]:
    """Bollinger Bands.

    Middle = SMA(period)
    Upper = Middle + (std_multiplier × StdDev)
    Lower = Middle - (std_multiplier × StdDev)
    """
    validated = _validate_prices(prices, min_periods=period)
    if not validated or len(validated) < period:
        return {"middle": None, "upper": None, "lower": None, "bandwidth": None}

    recent = validated[-period:]
    sma = sum(recent) / period

    variance = sum((p - sma) ** 2 for p in recent) / period
    std_dev = math.sqrt(variance)

    upper = round(sma + std_multiplier * std_dev, 4)
    lower = round(sma - std_multiplier * std_dev, 4)
    middle = round(sma, 4)
    bandwidth = round((upper - lower) / middle, 6) if middle != 0 else None

    return {"middle": middle, "upper": upper, "lower": lower, "bandwidth": bandwidth}


# ---------------------------------------------------------------------------
# ATR (Average True Range)
# ---------------------------------------------------------------------------


def compute_atr(candles: list[OHLCVData], period: int = 14) -> float | None:
    """Average True Range — measures market volatility."""
    if len(candles) < period + 1:
        return None

    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        high = candles[i].high
        low = candles[i].low
        prev_close = candles[i - 1].close

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    recent_tr = true_ranges[-period:]
    return round(sum(recent_tr) / period, 4)

# ---------------------------------------------------------------------------
# Stochastic Oscillator
# ---------------------------------------------------------------------------


def compute_stochastic(
    candles: list[OHLCVData], period: int = 14, smooth_k: int = 3, smooth_d: int = 3,
) -> dict[str, float | None]:
    """Stochastic Oscillator (%K and %D)."""
    if len(candles) < period + smooth_k + smooth_d:
        return {"k": None, "d": None}

    closes = _extract_closes(candles)
    highs = _extract_highs(candles)
    lows = _extract_lows(candles)

    raw_k = []
    for i in range(period, len(candles) + 1):
        highest_high = max(highs[i - period:i])
        lowest_low = min(lows[i - period:i])
        current_close = closes[i - 1]

        if highest_high == lowest_low:
            k = 50.0
        else:
            k = ((current_close - lowest_low) / (highest_high - lowest_low)) * 100
        raw_k.append(k)

    if len(raw_k) < smooth_k:
        return {"k": None, "d": None}

    smoothed_k = []
    for i in range(smooth_k, len(raw_k) + 1):
        smoothed_k.append(sum(raw_k[i-smooth_k:i]) / smooth_k)

    if len(smoothed_k) < smooth_d:
        return {"k": round(smoothed_k[-1], 2) if smoothed_k else None, "d": None}

    smoothed_d = sum(smoothed_k[-smooth_d:]) / smooth_d

    return {"k": round(smoothed_k[-1], 2), "d": round(smoothed_d, 2)}

# ---------------------------------------------------------------------------
# ADX (Average Directional Index) - simplified
# ---------------------------------------------------------------------------

def compute_adx(candles: list[OHLCVData], period: int = 14) -> float | None:
    """Simplified ADX calculation for trend strength."""
    if len(candles) < period * 2:
        return None
    try:
        import pandas as pd

        high = pd.Series([c.high for c in candles])
        low = pd.Series([c.low for c in candles])
        close = pd.Series([c.close for c in candles])

        plus_dm = high.diff()
        minus_dm = low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0

        tr1 = pd.DataFrame(high - low)
        tr2 = pd.DataFrame(abs(high - close.shift(1)))
        tr3 = pd.DataFrame(abs(low - close.shift(1)))
        frames = [tr1, tr2, tr3]
        tr = pd.concat(frames, axis=1, join='inner').max(axis=1)

        atr = tr.rolling(period).mean()
        plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
        minus_di = abs(100 * (minus_dm.rolling(period).mean() / atr))

        dx = (abs(plus_di - minus_di) / abs(plus_di + minus_di)) * 100
        adx = dx.rolling(period).mean()
        val = adx.iloc[-1]
        if pd.isna(val):
            return None
        return round(float(val), 2)
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        return None

# ---------------------------------------------------------------------------
# Time Series Metrics (Stationarity & STL)
# ---------------------------------------------------------------------------

def compute_time_series_metrics(candles: list[OHLCVData]) -> dict[str, Any]:
    """Compute ADF stationarity and STL decomposition metrics using statsmodels."""
    try:
        import pandas as pd
        from statsmodels.tsa.seasonal import STL
        from statsmodels.tsa.stattools import adfuller
    except ImportError:
        return {"stationarity": "unknown", "trend_strength": None, "seasonal_strength": None}

    if len(candles) < 30:
        return {"stationarity": "unknown", "trend_strength": None, "seasonal_strength": None}

    closes = _extract_closes(candles)
    series = pd.Series(closes)

    try:
        adf_result = adfuller(series.dropna())
        is_stationary = adf_result[1] < 0.05
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        is_stationary = False

    trend_strength = None
    seasonal_strength = None
    try:
        if len(series) >= 14:
            stl = STL(series, period=7, robust=True).fit()
            resid_var = stl.resid.var()
            if resid_var > 0:
                trend_strength = max(0.0, 1.0 - float(resid_var / (stl.trend + stl.resid).var()))
                seasonal_strength = max(0.0, 1.0 - float(resid_var / (stl.seasonal + stl.resid).var()))
            else:
                trend_strength = 1.0
                seasonal_strength = 1.0
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        pass

    return {
        "stationarity": "stationary" if is_stationary else "non-stationary",
        "trend_strength": round(trend_strength, 2) if trend_strength is not None else None,
        "seasonal_strength": round(seasonal_strength, 2) if seasonal_strength is not None else None,
    }


# ---------------------------------------------------------------------------
# Composite indicator computation
# ---------------------------------------------------------------------------


def compute_all_indicators(
    candles: list[OHLCVData],
) -> dict[str, Any]:
    """Compute a full suite of technical indicators from OHLCV data.

    Returns a dict with all indicator values. Individual indicators
    will be None if there isn't enough data to compute them.
    """
    if not candles:
        return {}

    closes = _extract_closes(candles)
    volumes = _extract_volumes(candles)

    current_price = closes[-1] if closes else 0.0

    # Price-based indicators
    sma_20 = compute_sma(closes, 20)
    sma_50 = compute_sma(closes, 50)
    sma_200 = compute_sma(closes, 200)
    ema_12 = compute_ema(closes, 12)
    ema_26 = compute_ema(closes, 26)

    # Oscillators
    rsi_14 = compute_rsi(closes, 14)
    macd = compute_macd(closes)

    # Volatility
    bb = compute_bollinger_bands(closes, 20)
    atr_14 = compute_atr(candles, 14)

    # Advanced Momentum / Trend
    stoch = compute_stochastic(candles)
    adx_14 = compute_adx(candles, 14)

    # Time Series Stats
    ts_metrics = compute_time_series_metrics(candles)

    # Volume
    volume_sma = compute_sma(volumes, 20) if len(volumes) >= 20 else None
    current_volume = volumes[-1] if volumes else 0.0

    # Trend identification
    trend: str = "neutral"
    if sma_50 is not None and sma_200 is not None:
        if sma_50 > sma_200 and current_price > sma_50:
            trend = "bullish"
        elif sma_50 < sma_200 and current_price < sma_50:
            trend = "bearish"

    # Support / Resistance (simple local min/max)
    support_levels = _find_support_levels(closes, 3)
    resistance_levels = _find_resistance_levels(closes, 3)

    # Candlestick Patterns
    candlestick_patterns = detect_candlestick_patterns(candles)

    return {
        "current_price": current_price,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "ema_12": ema_12,
        "ema_26": ema_26,
        "rsi_14": rsi_14,
        "stochastic": stoch,
        "macd": macd,
        "bollinger_bands": bb,
        "atr_14": atr_14,
        "adx_14": adx_14,
        "volume_sma_20": volume_sma,
        "current_volume": current_volume,
        "trend": trend,
        "support_levels": support_levels,
        "resistance_levels": resistance_levels,
        "time_series": ts_metrics,
        "candlestick_patterns": candlestick_patterns,
        "high_52w": max(closes) if closes else None,
        "low_52w": min(closes) if closes else None,
        "price_change_1d": round(((closes[-1] - closes[-2]) / closes[-2]) * 100, 2) if len(closes) >= 2 else None,
        "price_change_1w": round(((closes[-1] - closes[-7]) / closes[-7]) * 100, 2) if len(closes) >= 8 else None,
    }


def _find_support_levels(prices: list[float], lookback: int = 3) -> list[float]:
    """Find local minima as support levels."""
    if len(prices) < lookback * 2 + 1:
        return []
    levels = []
    for i in range(lookback, len(prices) - lookback):
        window = prices[i - lookback : i + lookback + 1]
        if prices[i] == min(window):
            levels.append(round(prices[i], 2))
    # Return most recent levels, deduped
    seen: set[float] = set()
    unique = []
    for level in reversed(levels):
        if level not in seen:
            seen.add(level)
            unique.append(level)
    return unique[:3]


def _find_resistance_levels(prices: list[float], lookback: int = 3) -> list[float]:
    """Find local maxima as resistance levels."""
    if len(prices) < lookback * 2 + 1:
        return []
    levels = []
    for i in range(lookback, len(prices) - lookback):
        window = prices[i - lookback : i + lookback + 1]
        if prices[i] == max(window):
            levels.append(round(prices[i], 2))
    seen: set[float] = set()
    unique = []
    for level in reversed(levels):
        if level not in seen:
            seen.add(level)
            unique.append(level)
    return unique[:3]
