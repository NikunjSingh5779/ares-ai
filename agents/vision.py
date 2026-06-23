"""Vision Agent — chart pattern analysis (advisory, non-blocking).

Analyzes OHLCV data to detect support/resistance levels and chart patterns
using deterministic rules. Optionally enhances with vision model analysis
when chart images are available.

Per CLAUDE.md:
- Vision Agent feeds chart-pattern confirmation into the Consensus Engine
  in parallel with Market Analyst; it is advisory, not blocking.
- If the vision model is unavailable, sets ``available=False`` and returns
  rule-based analysis only — the pipeline never blocks on vision.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agents.state import VisionOutput
from agents.base import AgentContext, BaseAgent


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class VisionInput(BaseModel):
    """Input for the Vision Agent.

    Accepts either raw OHLCV data for rule-based pattern detection, or
    chart image URLs for LLM-powered vision analysis.
    """

    symbol: str = Field(default="", description="Ticker symbol")
    candles: list[dict[str, Any]] = Field(
        default_factory=list,
        description="OHLCV candles as dicts with open/high/low/close/volume keys",
    )
    chart_image_urls: list[str] = Field(
        default_factory=list,
        description="Optional chart screenshot URLs for vision model analysis",
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOOKBACK_LEVELS: int = 30
"""Number of recent candles to scan for support/resistance."""

SUPPORT_RESISTANCE_BINS: int = 10
"""Number of price bins for clustering support/resistance levels."""

PATTERN_MIN_CONSECUTIVE: int = 3
"""Minimum consecutive higher/lower closes for trend pattern detection."""


# ---------------------------------------------------------------------------
# Vision Agent
# ---------------------------------------------------------------------------


class VisionAgent(BaseAgent[VisionInput, VisionOutput]):
    """Chart pattern analysis agent — advisory, non-blocking.

    Rule-based analysis (always available):
    1. Detect support and resistance levels from recent price action
    2. Identify basic chart patterns (uptrend, downtrend, consolidation)
    3. Score pattern confidence based on clarity

    Optional vision model enhancement:
    - When chart image URLs are provided and a vision model is configured,
      sends images for LLM interpretation
    - Graceful degradation: if model unavailable, sets ``available=False``

    Usage::

        agent = VisionAgent()
        result = await agent.run(VisionInput(symbol="BTC-USD", candles=[...]))
    """

    agent_name: str = "vision"
    input_schema: type[BaseModel] = VisionInput
    output_schema: type[BaseModel] = VisionOutput

    def __init__(
        self,
        context: AgentContext | None = None,
        model_available: bool = False,
    ) -> None:
        super().__init__(context=context)
        self.model_available = model_available

    async def process(self, inputs: VisionInput) -> dict[str, Any]:
        """Execute chart pattern analysis.

        Always runs rule-based detection. If chart images are provided and
        a vision model is available, enhances with model analysis.
        """
        symbol = inputs.symbol or "unknown"
        candles = inputs.candles

        # ── Rule-based pattern detection ──────────────────────────────
        support_levels = _detect_support_levels(candles)
        resistance_levels = _detect_resistance_levels(candles)
        chart_pattern, pattern_confidence = _detect_chart_pattern(candles)
        pattern_rationale = _build_pattern_rationale(
            chart_pattern, support_levels, resistance_levels,
        )

        # ── Vision model enhancement (optional) ───────────────────────
        model_available = self.model_available and bool(inputs.chart_image_urls)
        model_rationale: str | None = None

        if model_available:
            try:
                model_rationale = await self._analyze_with_model(inputs)
            except Exception:
                model_available = False  # Graceful degradation

        # ── Build output ──────────────────────────────────────────────
        rationale_parts = [pattern_rationale]
        if model_rationale:
            rationale_parts.append(model_rationale)

        return {
            "chart_pattern": chart_pattern,
            "confidence": round(pattern_confidence, 1),
            "support_levels": [round(l, 4) for l in support_levels[:3]],
            "resistance_levels": [round(l, 4) for l in resistance_levels[:3]],
            "available": model_available,
            "rationale": " | ".join(rationale_parts),
        }

    async def _analyze_with_model(self, inputs: VisionInput) -> str:
        """Send chart images to the vision model for interpretation.

        Override this method in subclasses to integrate with specific
        vision model APIs. Default implementation returns a placeholder.

        This method should never raise — catch exceptions and return a
        degradation message instead.
        """
        # Default: no model integration yet
        # Subclasses can override to call CLIP, GPT-4V, or other VL models
        return "Vision model analysis not configured — using rule-based results only"


# ---------------------------------------------------------------------------
# Pattern detection helpers
# ---------------------------------------------------------------------------


def _detect_support_levels(candles: list[dict[str, Any]]) -> list[float]:
    """Detect support levels from price lows using clustering.

    Groups recent lows into price bins and returns the most frequent
    levels sorted by frequency (most significant first).
    """
    if not candles:
        return []

    lows = [float(c.get("low", 0)) for c in candles[-LOOKBACK_LEVELS:] if c.get("low")]
    if not lows:
        return []

    return _cluster_levels(lows, ascending=True)


def _detect_resistance_levels(candles: list[dict[str, Any]]) -> list[float]:
    """Detect resistance levels from price highs using clustering."""
    if not candles:
        return []

    highs = [float(c.get("high", 0)) for c in candles[-LOOKBACK_LEVELS:] if c.get("high")]
    if not highs:
        return []

    return _cluster_levels(highs, ascending=False)


def _cluster_levels(prices: list[float], ascending: bool) -> list[float]:
    """Cluster price points into levels using equal-width binning.

    Args:
        prices: List of price values (lows or highs).
        ascending: Sort result ascending (support) or descending (resistance).

    Returns:
        Sorted list of level prices, most significant (most frequent bin) first.
    """
    if not prices:
        return []

    price_min = min(prices)
    price_max = max(prices)
    if price_max == price_min:
        return [price_min]

    bin_width = (price_max - price_min) / SUPPORT_RESISTANCE_BINS
    if bin_width == 0:
        return [price_min]

    bins: dict[int, list[float]] = {}
    for p in prices:
        bin_idx = min(int((p - price_min) / bin_width), SUPPORT_RESISTANCE_BINS - 1)
        if bin_idx not in bins:
            bins[bin_idx] = []
        bins[bin_idx].append(p)

    # Sort bins by count (most frequent first)
    sorted_bins = sorted(bins.items(), key=lambda x: len(x[1]), reverse=True)

    # Take the median price of each bin as the level
    levels = []
    for _, bin_prices in sorted_bins[:3]:
        bin_prices.sort()
        median = bin_prices[len(bin_prices) // 2]
        levels.append(median)

    return sorted(levels, reverse=not ascending)


def _detect_chart_pattern(candles: list[dict[str, Any]]) -> tuple[str, float]:
    """Detect the dominant chart pattern from recent price action.

    Returns (pattern_name, confidence_0_to_100).

    Patterns detected:
    - "uptrend": Consecutive higher highs and higher lows
    - "downtrend": Consecutive lower highs and lower lows
    - "consolidation": Price in a narrow range with no clear direction
    - "flat": Insufficient data or no clear pattern
    """
    if not candles or len(candles) < PATTERN_MIN_CONSECUTIVE:
        return "flat", 0.0

    recent = candles[-PATTERN_MIN_CONSECUTIVE:]

    closes = [float(c.get("close", 0)) for c in recent]
    highs = [float(c.get("high", 0)) for c in recent]
    lows = [float(c.get("low", 0)) for c in recent]

    if not all(closes) or not all(highs) or not all(lows):
        return "flat", 0.0

    # Trend detection
    higher_highs = all(highs[i] <= highs[i + 1] for i in range(len(highs) - 1))
    lower_highs = all(highs[i] >= highs[i + 1] for i in range(len(highs) - 1))
    higher_lows = all(lows[i] <= lows[i + 1] for i in range(len(lows) - 1))
    lower_lows = all(lows[i] >= lows[i + 1] for i in range(len(lows) - 1))

    if higher_highs and higher_lows:
        return "uptrend", _score_trend_confidence(closes, highs, lows)

    if lower_highs and lower_lows:
        return "downtrend", _score_trend_confidence(closes, highs, lows)

    # Consolidation detection: tight range
    price_range = (max(highs) - min(lows)) / min(lows)
    if price_range < 0.03:  # Less than 3% range over the period
        return "consolidation", 60.0

    return "flat", 20.0


def _score_trend_confidence(
    closes: list[float],
    highs: list[float],
    lows: list[float],
) -> float:
    """Score trend confidence based on momentum strength.

    Higher score = stronger, clearer trend.
    """
    if len(closes) < 2:
        return 30.0

    close_change = abs(closes[-1] - closes[0]) / (closes[0] or 0.001)

    # Stronger price change = higher confidence
    if close_change > 0.05:  # >5% move
        return 85.0
    if close_change > 0.03:  # >3% move
        return 70.0
    if close_change > 0.01:  # >1% move
        return 55.0

    return 40.0


def _build_pattern_rationale(
    pattern: str,
    support: list[float],
    resistance: list[float],
) -> str:
    """Build a human-readable rationale for the detected pattern."""
    parts = [f"Chart pattern: {pattern}"]

    if support:
        s_str = ", ".join(f"${l:.2f}" for l in support[:2])
        parts.append(f"support at {s_str}")
    if resistance:
        r_str = ", ".join(f"${l:.2f}" for l in resistance[:2])
        parts.append(f"resistance at {r_str}")

    return " | ".join(parts) if len(parts) > 1 else parts[0]
