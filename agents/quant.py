"""Quant Agent — quantitative analysis with strategy generation.

Follows the MarketAnalystAgent pattern with additional strategy selection,
expected return projection, and strategy parameters.

Strategies (evaluated by rule-based fallback):
- momentum: trend-following via SMA crossovers
- mean_reversion: contrarian bets at RSI extremes
- trend_following: MACD-confirmed trend continuation
- breakout: volume-confirmed Bollinger Band breaks
- neutral: no clear signal
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from agents.base import AgentContext, BaseAgent
from agents.indicators import compute_all_indicators
from agents.router import ModelRouter, RouterResult
from backend.data.ingestor import MarketDataIngestor
from backend.data.models import OHLCVData


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class QuantInput(BaseModel):
    """Input for the Quant Agent.

    Can receive either pre-fetched candles or enough info to fetch them.
    The optional strategy field hints which strategy to evaluate.
    """

    symbol: str = Field(..., description="Ticker symbol (e.g. BTC-USD, AAPL)")
    interval: str = Field(default="1d", description="Candle interval")
    lookback: int = Field(default=100, description="Number of candles to analyze")
    candles: list[OHLCVData] | None = Field(
        default=None,
        description="Pre-fetched OHLCV data (bypasses ingestor)",
    )
    strategy: str | None = Field(
        default=None,
        description="Suggested strategy hint (momentum, mean_reversion, trend_following, breakout)",
    )
    market_analyst_result: dict[str, Any] | None = Field(
        default=None,
        description="Output from MarketAnalystAgent for additional context",
    )


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

QUANT_SYSTEM_PROMPT = """You are the Quant Agent in the ARES AI trading system.

Your role: Analyze market indicators and recent price action, select a quantitative
trading strategy, and produce a structured signal with expected return projection.

Available strategies:
- momentum: Enter in the direction of the prevailing trend. Best when trend is strong
  and RSI confirms (not overbought/oversold).
- mean_reversion: Bet on price returning to the mean. Best when RSI is extreme (>70 or <30)
  and price is touching Bollinger Bands.
- trend_following: Follow the established trend direction with MACD confirmation.
- breakout: Trade breakouts from Bollinger Bands or support/resistance with volume confirmation.
- neutral: No clear signal. Use as default when confidence is low.

Rules:
1. Return ONLY valid JSON — no markdown, no explanation outside the JSON.
2. Your JSON must match this schema exactly:
   {{
     "confidence": <float 0-100>,
     "direction": <"long" | "short" | "flat">,
     "expected_return": <float | null, estimated return % for this trade>,
     "strategy_name": <"momentum" | "mean_reversion" | "trend_following" | "breakout" | "neutral">,
     "params": {{
       "lookback": <int, strategy lookback period>,
       "entry_threshold": <float | null>,
       "exit_threshold": <float | null>,
       "stop_loss_pct": <float | null>,
       "risk_per_trade_pct": <float | null>
     }},
     "rationale": "<string explaining your quantitative reasoning>"
   }}
3. confidence < 50 means you are uncertain — prefer "flat" with strategy "neutral".
4. Consider: trend strength, momentum (RSI), volatility (ATR, Bollinger Bands), volume profile.
5. expected_return should be estimated conservatively. Base it on recent ATR and volatility.
6. If market analyst context is provided, weigh it but do not copy it — apply your own
   quantitative framework.
7. Be conservative. It is better to miss a trade than to take a bad one."""


def build_quant_prompt(
    symbol: str,
    indicators: dict[str, Any],
    recent_candles: list[OHLCVData],
    strategy_hint: str | None = None,
    market_analyst_result: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build the messages for the LLM quant analysis call.

    Args:
        symbol: Ticker symbol.
        indicators: Output from compute_all_indicators().
        recent_candles: Last 20-30 OHLCV candles for context.
        strategy_hint: Optional strategy name to evaluate.
        market_analyst_result: Optional MarketAnalystAgent output.

    Returns:
        List of {"role": ..., "content": ...} dicts for the LLM call.
    """
    # Format recent price data
    recent_lines = []
    for c in recent_candles[-20:]:
        recent_lines.append(
            f"  {c.timestamp.strftime('%Y-%m-%d')}: "
            f"O={c.open:.2f} H={c.high:.2f} L={c.low:.2f} "
            f"C={c.close:.2f} V={c.volume:.1f}"
        )
    price_summary = "\n".join(recent_lines)

    # Format indicators
    ind_lines = []
    ind_lines.append(f"Current Price: ${indicators.get('current_price', 'N/A')}")
    ind_lines.append(f"Trend: {indicators.get('trend', 'neutral')}")

    if indicators.get("sma_20") is not None:
        ind_lines.append(f"SMA(20): ${indicators['sma_20']:.2f}")
    if indicators.get("sma_50") is not None:
        ind_lines.append(f"SMA(50): ${indicators['sma_50']:.2f}")
    if indicators.get("sma_200") is not None:
        ind_lines.append(f"SMA(200): ${indicators['sma_200']:.2f}")
    if indicators.get("rsi_14") is not None:
        ind_lines.append(f"RSI(14): {indicators['rsi_14']:.1f}")
    if indicators.get("macd", {}).get("macd") is not None:
        macd = indicators["macd"]
        ind_lines.append(
            f"MACD: {macd['macd']} / Signal: {macd.get('signal', 'N/A')} "
            f"/ Histogram: {macd.get('histogram', 'N/A')}"
        )
    if indicators.get("bollinger_bands", {}).get("middle") is not None:
        bb = indicators["bollinger_bands"]
        ind_lines.append(
            f"Bollinger Bands: Mid={bb['middle']:.2f} Upper={bb['upper']:.2f} "
            f"Lower={bb['lower']:.2f}"
        )
    if indicators.get("atr_14") is not None:
        ind_lines.append(f"ATR(14): ${indicators['atr_14']:.2f}")
        atr_ratio = _atr_ratio(indicators)
        if atr_ratio is not None:
            ind_lines.append(f"ATR as % of price: {atr_ratio:.2f}%")
    if indicators.get("volume_sma_20") is not None:
        vol_ratio = _volume_ratio(indicators)
        ind_lines.append(f"Volume vs SMA(20): {'{:.1f}x'.format(vol_ratio) if vol_ratio else 'N/A'}")

    indicator_summary = "\n".join(ind_lines)

    # Build user content
    user_parts = [
        f"Symbol: {symbol}",
        f"Interval: Daily",
        f"Date Range: {recent_candles[0].timestamp.strftime('%Y-%m-%d') if recent_candles else 'N/A'} "
        f"to {recent_candles[-1].timestamp.strftime('%Y-%m-%d') if recent_candles else 'N/A'}",
    ]

    if strategy_hint:
        user_parts.append(f"\nSuggested strategy to evaluate: {strategy_hint}")

    if market_analyst_result:
        ma_direction = market_analyst_result.get("direction", "unknown")
        ma_confidence = market_analyst_result.get("confidence", "unknown")
        ma_rationale = market_analyst_result.get("rationale", "")
        user_parts.append(
            f"\nMarket Analyst assessment:\n"
            f"  Direction: {ma_direction}\n"
            f"  Confidence: {ma_confidence}\n"
            f"  Rationale: {ma_rationale}"
        )

    user_parts.append(f"\n--- Recent Price Data ---\n{price_summary}")
    user_parts.append(f"\n--- Technical Indicators ---\n{indicator_summary}")
    user_parts.append(
        "\nAnalyze the above, select a strategy, and return your trading "
        "signal as valid JSON matching the specified schema."
    )

    return [
        {"role": "system", "content": QUANT_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


# ---------------------------------------------------------------------------
# Rule-based quant analysis (degraded mode)
# ---------------------------------------------------------------------------

VALID_STRATEGIES = frozenset({
    "momentum", "mean_reversion", "trend_following", "breakout", "neutral",
})


def _rule_based_quant(
    symbol: str,
    indicators: dict[str, Any],
    strategy_hint: str | None = None,
) -> dict[str, Any]:
    """Rule-based quantitative signal generation when LLM is unavailable.

    Evaluates all available strategies and picks the one with the strongest
    signal. Computes expected return estimates based on ATR.

    Returns a dict matching QuantOutput schema.
    """
    candidates: list[dict[str, Any]] = []

    # Evaluate all strategies
    if _detect_momentum(indicators):
        candidates.append(_build_momentum_signal(indicators))
    if _detect_mean_reversion(indicators):
        candidates.append(_build_mean_reversion_signal(indicators))
    if _detect_trend_following(indicators):
        candidates.append(_build_trend_following_signal(indicators))
    if _detect_breakout(indicators):
        candidates.append(_build_breakout_signal(indicators))

    if not candidates:
        return _build_neutral_signal(indicators)

    # Sort by confidence descending
    candidates.sort(key=lambda c: c["confidence"], reverse=True)

    # If strategy_hint specified, prefer it among candidates
    if strategy_hint and strategy_hint in VALID_STRATEGIES:
        match = next(
            (c for c in candidates if c["strategy_name"] == strategy_hint),
            None,
        )
        if match:
            return match

    return candidates[0]


# ---------------------------------------------------------------------------
# Strategy detectors
# ---------------------------------------------------------------------------

def _detect_momentum(indicators: dict[str, Any]) -> bool:
    """Momentum strategy trigger: SMA crossover with non-extreme RSI."""
    sma_20 = indicators.get("sma_20")
    sma_50 = indicators.get("sma_50")
    rsi = indicators.get("rsi_14")
    if sma_20 is None or sma_50 is None or rsi is None:
        return False
    # Require meaningful SMA separation and non-extreme RSI
    spread = abs(sma_20 - sma_50) / max(sma_50, 1)
    return spread > 0.005 and 30 <= rsi <= 70


def _detect_mean_reversion(indicators: dict[str, Any]) -> bool:
    """Mean reversion trigger: RSI at extremes."""
    rsi = indicators.get("rsi_14")
    if rsi is None:
        return False
    return rsi < 30 or rsi > 70


def _detect_trend_following(indicators: dict[str, Any]) -> bool:
    """Trend following trigger: clear trend + MACD confirmation."""
    trend = indicators.get("trend", "neutral")
    if trend == "neutral":
        return False
    macd = indicators.get("macd", {})
    histogram = macd.get("histogram")
    if histogram is None:
        return False
    if trend == "bullish":
        return histogram > 0
    return histogram < 0


def _detect_breakout(indicators: dict[str, Any]) -> bool:
    """Breakout trigger: high volume at Bollinger Band edge."""
    vol_ratio = _volume_ratio(indicators)
    if vol_ratio is None or vol_ratio < 1.5:
        return False
    current_price = indicators.get("current_price", 0)
    bb = indicators.get("bollinger_bands", {})
    upper = bb.get("upper")
    lower = bb.get("lower")
    if upper is not None and current_price >= upper:
        return True
    if lower is not None and current_price <= lower:
        return True
    return False


# ---------------------------------------------------------------------------
# Signal builders
# ---------------------------------------------------------------------------

def _atr_ratio(indicators: dict[str, Any]) -> float | None:
    """ATR as percentage of current price."""
    atr = indicators.get("atr_14")
    price = indicators.get("current_price", 0)
    if atr is not None and price > 0:
        return atr / price * 100
    return None


def _volume_ratio(indicators: dict[str, Any]) -> float | None:
    """Ratio of current volume to 20-period SMA of volume."""
    current_vol = indicators.get("current_volume")
    avg_vol = indicators.get("volume_sma_20")
    if current_vol is not None and avg_vol is not None and avg_vol > 0:
        return current_vol / avg_vol
    return None


def _build_momentum_signal(indicators: dict[str, Any]) -> dict[str, Any]:
    """Build signal for momentum strategy."""
    sma_20 = indicators.get("sma_20", 0)
    sma_50 = indicators.get("sma_50", 0)
    is_bullish = sma_20 > sma_50 if (sma_20 and sma_50) else True
    direction = "long" if is_bullish else "short"
    price = indicators.get("current_price", 0)
    atr_pct = _atr_ratio(indicators)

    confidence = 55.0 + (5.0 if atr_pct and atr_pct > 1.0 else 0.0)
    expected_return = round(atr_pct * 2.0, 2) if atr_pct else None

    return {
        "confidence": min(confidence, 80.0),
        "direction": direction,
        "expected_return": expected_return,
        "strategy_name": "momentum",
        "params": {
            "lookback": 20,
            "entry_threshold": round(sma_20, 2) if sma_20 else None,
            "exit_threshold": round(sma_50, 2) if sma_50 else None,
            "stop_loss_pct": round(atr_pct * 1.5, 2) if atr_pct else None,
            "risk_per_trade_pct": 2.0,
        },
        "rationale": (
            f"Momentum strategy: SMA(20) {'>' if is_bullish else '<'} SMA(50) "
            f"signals {'bullish' if is_bullish else 'bearish'} momentum"
        ),
    }


def _build_mean_reversion_signal(indicators: dict[str, Any]) -> dict[str, Any]:
    """Build signal for mean reversion strategy."""
    rsi = indicators.get("rsi_14", 50)
    is_oversold = rsi < 30
    direction = "long" if is_oversold else "short"
    price = indicators.get("current_price", 0)
    bb = indicators.get("bollinger_bands", {})
    bb_mid = bb.get("middle")

    # Expected return = distance to mean / price * 0.5
    expected_return = None
    if bb_mid is not None and price > 0:
        retrace = abs(price - bb_mid) / price * 0.5
        expected_return = round(retrace * 100, 2)

    rsi_extreme = rsi if is_oversold else (100 - rsi)
    confidence = min(55.0 + (70 - rsi_extreme) * 0.5, 75.0)

    return {
        "confidence": confidence,
        "direction": direction,
        "expected_return": expected_return,
        "strategy_name": "mean_reversion",
        "params": {
            "lookback": 14,
            "entry_threshold": round(rsi, 1),
            "exit_threshold": 50.0,
            "stop_loss_pct": round(abs(price - bb.get("lower", price)) / price * 100, 2)
                if is_oversold and bb.get("lower")
                else round(abs(bb.get("upper", price) - price) / price * 100, 2)
                if not is_oversold and bb.get("upper")
                else None,
            "risk_per_trade_pct": 1.5,
        },
        "rationale": (
            f"Mean reversion strategy: RSI={rsi:.1f} signals "
            f"{'oversold bounce' if is_oversold else 'overbought pullback'}"
        ),
    }


def _build_trend_following_signal(indicators: dict[str, Any]) -> dict[str, Any]:
    """Build signal for trend following strategy."""
    trend = indicators.get("trend", "neutral")
    direction = "long" if trend == "bullish" else "short"
    atr_pct = _atr_ratio(indicators)
    macd = indicators.get("macd", {})

    expected_return = round(atr_pct * 1.5, 2) if atr_pct else None
    confidence = 60.0 + (5.0 if atr_pct and atr_pct > 1.0 else 0.0)

    return {
        "confidence": min(confidence, 80.0),
        "direction": direction,
        "expected_return": expected_return,
        "strategy_name": "trend_following",
        "params": {
            "lookback": 26,
            "entry_threshold": macd.get("macd"),
            "exit_threshold": macd.get("signal"),
            "stop_loss_pct": round(atr_pct * 2.0, 2) if atr_pct else None,
            "risk_per_trade_pct": 2.0,
        },
        "rationale": (
            f"Trend following: {trend} trend with MACD "
            f"{'positive' if macd.get('histogram', 0) > 0 else 'negative'} histogram"
        ),
    }


def _build_breakout_signal(indicators: dict[str, Any]) -> dict[str, Any]:
    """Build signal for breakout strategy."""
    price = indicators.get("current_price", 0)
    bb = indicators.get("bollinger_bands", {})
    upper = bb.get("upper", 0)
    lower = bb.get("lower", 0)
    mid = bb.get("middle", 0)

    breaking_upper = upper and price >= upper
    direction = "short" if breaking_upper else "long"
    bandwidth = ((upper - lower) / mid) if (mid and mid != 0) else 0

    expected_return = round(bandwidth * 0.5 * 100, 2) if bandwidth else None
    confidence = 60.0

    return {
        "confidence": confidence,
        "direction": direction,
        "expected_return": expected_return,
        "strategy_name": "breakout",
        "params": {
            "lookback": 20,
            "entry_threshold": round(upper, 2) if upper else None,
            "exit_threshold": round(mid, 2) if mid else None,
            "stop_loss_pct": round(bandwidth * 0.3 * 100, 2) if bandwidth else None,
            "risk_per_trade_pct": 2.0,
        },
        "rationale": (
            f"Breakout strategy: Price {'breaking above upper' if breaking_upper else 'breaking below lower'} "
            f"Bollinger Band with elevated volume ({_volume_ratio(indicators):.1f}x)"
        ),
    }


def _build_neutral_signal(indicators: dict[str, Any]) -> dict[str, Any]:
    """Build neutral signal when no strategy triggers."""
    return {
        "confidence": 20.0,
        "direction": "flat",
        "expected_return": None,
        "strategy_name": "neutral",
        "params": {
            "lookback": 20,
            "entry_threshold": None,
            "exit_threshold": None,
            "stop_loss_pct": None,
            "risk_per_trade_pct": None,
        },
        "rationale": "No clear quantitative signal detected across any strategy",
    }


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _strip_markdown_fences(text: str) -> str:
    """Strip markdown code fences from a string."""
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_quant_response(
    response_text: str | None,
    fallback_result: dict[str, Any],
) -> dict[str, Any]:
    """Parse LLM response text into a structured QuantOutput-compatible dict.

    If parsing fails, returns the fallback result.
    """
    if not response_text:
        return fallback_result

    text = _strip_markdown_fences(response_text.strip())

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return fallback_result

    # Validate required fields
    required_fields = {"confidence", "direction", "rationale"}
    if not required_fields.issubset(data.keys()):
        return fallback_result

    if data.get("direction") not in ("long", "short", "flat"):
        return fallback_result

    # Clamp confidence
    confidence = max(0.0, min(100.0, float(data.get("confidence", 0))))

    # Validate strategy_name
    strategy = data.get("strategy_name", "neutral")
    if strategy not in VALID_STRATEGIES:
        strategy = "neutral"

    # Validate expected_return
    expected_return = data.get("expected_return")
    if expected_return is not None:
        try:
            expected_return = float(expected_return)
        except (ValueError, TypeError):
            expected_return = None

    # Validate params
    params = data.get("params", {})
    if not isinstance(params, dict):
        params = {}

    rationale = str(data.get("rationale", "")) or fallback_result.get("rationale", "")

    # Fill in missing fields from fallback
    if expected_return is None and fallback_result.get("expected_return") is not None:
        expected_return = fallback_result["expected_return"]
    if strategy == "neutral" and fallback_result.get("strategy_name", "neutral") != "neutral":
        strategy = fallback_result["strategy_name"]

    return {
        "confidence": confidence,
        "direction": data["direction"],
        "expected_return": expected_return,
        "strategy_name": strategy,
        "params": {**fallback_result.get("params", {}), **params},
        "rationale": rationale,
    }


# ---------------------------------------------------------------------------
# QuantAgent
# ---------------------------------------------------------------------------

class QuantAgent(BaseAgent[QuantInput, dict]):
    """Quantitative analysis agent combining technical indicators with LLM-based
    strategy generation and expected return projection.

    Two-tier analysis:
    1. Compute technical indicators from OHLCV data
    2. Send indicators + market data to LLM via ModelRouter for quantitative analysis
    3. If LLM unavailable or returns invalid output, fall back to rule-based quant
    4. Return structured QuantOutput-compatible dict

    Usage:
        agent = QuantAgent(router=router, ingestor=ingestor)
        result = await agent.run(QuantInput(symbol="BTC-USD"))
    """

    agent_name: str = "quant"
    input_schema: type[BaseModel] = QuantInput

    def __init__(
        self,
        router: ModelRouter,
        ingestor: MarketDataIngestor | None = None,
        context: AgentContext | None = None,
    ) -> None:
        super().__init__(context=context)
        self.router = router
        self.ingestor = ingestor

    async def process(self, inputs: QuantInput) -> dict[str, Any]:
        """Execute quantitative analysis.

        1. Fetch/validate OHLCV data
        2. Compute technical indicators
        3. Attempt LLM-based quant analysis with strategy selection
        4. Fall back to rule-based quant if LLM unavailable
        5. Return structured result
        """
        # Step 1: Get candle data
        candles = await self._get_candles(inputs)
        if not candles:
            return {
                "confidence": 0.0,
                "direction": "flat",
                "expected_return": None,
                "strategy_name": "neutral",
                "params": {},
                "rationale": f"No market data available for {inputs.symbol}",
            }

        # Step 2: Compute indicators
        indicators = compute_all_indicators(candles)

        # Step 3: Try LLM analysis
        llm_result = await self._llm_quant(
            inputs.symbol,
            indicators,
            candles,
            strategy_hint=inputs.strategy,
            market_analyst_result=inputs.market_analyst_result,
        )

        # Step 4: Fall back to rule-based if needed
        if llm_result is None:
            llm_result = _rule_based_quant(
                inputs.symbol,
                indicators,
                strategy_hint=inputs.strategy,
            )

        return llm_result

    async def _get_candles(self, inputs: QuantInput) -> list[OHLCVData]:
        """Get OHLCV data — either pre-fetched or via ingestor."""
        if inputs.candles:
            return inputs.candles

        if self.ingestor is not None:
            try:
                result = await self.ingestor.ingest(
                    symbol=inputs.symbol,
                    source="yahoo",
                    interval=inputs.interval,
                    limit=inputs.lookback,
                )
                return result.candles
            except Exception:
                return []

        return []

    async def _llm_quant(
        self,
        symbol: str,
        indicators: dict[str, Any],
        candles: list[OHLCVData],
        strategy_hint: str | None = None,
        market_analyst_result: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Attempt LLM-based quant analysis. Returns None if unavailable."""
        # Build the prompt
        messages = build_quant_prompt(
            symbol,
            indicators,
            candles,
            strategy_hint=strategy_hint,
            market_analyst_result=market_analyst_result,
        )

        # Get agent model config from context
        try:
            model_chain = self.context.model_preferences.get("model_chain", [])
            rpm = self.context.model_preferences.get("rpm", 10)
            temperature = self.context.model_preferences.get("temperature", 0.3)
            max_tokens = self.context.model_preferences.get("max_tokens", 1024)
        except Exception:
            model_chain = []
            rpm = 10
            temperature = 0.3
            max_tokens = 1024

        if not model_chain:
            return None

        # Execute via model router
        router_result: RouterResult = await self.router.execute(
            model_chain=model_chain,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            rpm=rpm,
        )

        if not router_result.success or router_result.degraded:
            return None

        # Parse the response
        response_text = None
        if router_result.response:
            try:
                response_text = router_result.response["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                pass

        fallback = _rule_based_quant(symbol, indicators, strategy_hint=strategy_hint)
        return _parse_quant_response(response_text, fallback)
