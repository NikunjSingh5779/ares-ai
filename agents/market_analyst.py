"""Market Analyst Agent — technical + LLM-powered market analysis.

The first real agent implementation in the ARES AI pipeline.
Computes technical indicators, sends them to an LLM for analysis,
and falls back to rule-based analysis when the LLM is unavailable.

Implements the CLAUDE.md AGENT I/O CONTRACTS:
- Typed input/output schemas (Pydantic)
- Output validated on receipt
- rationale/explanation fields required for trading-relevant numbers
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from agents.base import AgentContext, BaseAgent
from agents.indicators import compute_all_indicators
from agents.router import ModelRouter, RouterResult
from agents.state import MarketAnalystOutput
from backend.core.metrics import record_agent_fallback
from backend.data.ingestor import MarketDataIngestor
from backend.data.models import MarketDataRequest, OHLCVData

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------
class MarketAnalystInput(BaseModel):
    """Input for the Market Analyst Agent.
    Can receive either pre-fetched candles or enough info to fetch them.
    """

    symbol: str = Field(..., description="Ticker symbol (e.g. BTC-USD, AAPL)")
    interval: str = Field(default="1d", description="Candle interval")
    lookback: int = Field(default=100, description="Number of candles to analyze")
    candles: list[OHLCVData] | None = Field(
        default=None,
        description="Pre-fetched OHLCV data (bypasses ingestor)",
    )


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are the Market Analyst Agent in the ARES AI trading system.
Your role: Analyze the provided market data and technical indicators, then
produce a structured trading signal.
Rules:
1. Return ONLY valid JSON — no markdown, no explanation outside the JSON.
2. Your JSON must match this schema exactly:
   {
     "confidence": <float 0-100, how confident you are in this signal>,
     "direction": <"long" | "short" | "flat">,
     "bias": <"bullish" | "bearish" | "neutral">,
     "setup": <"pattern or indicator trigger">,
     "entry_zone": <"Entry zone or exact level">,
     "stop_loss": <"Stop loss level">,
     "targets": ["Target 1", "Target 2"],
     "invalidation": <"What would prove this thesis wrong">,
     "confluence": <"List of confirming factors">,
     "indicators": { <indicator_name>: <value>, ... },
     "rationale": "<string explaining your reasoning>"
   }
3. confidence < 50 means you're uncertain — prefer "flat" in that case.
4. Consider: market structure (higher highs, lower lows), candlestick patterns, trend,
   momentum (RSI), volatility (Bollinger Bands), volume, Stochastic, ADX, and Time Series
   metrics.
5. Be conservative. It's better to miss a trade than to take a bad one."""


def build_analysis_prompt(
    symbol: str,
    indicators: dict[str, Any],
    recent_candles: list[OHLCVData],
) -> list[dict[str, str]]:
    """Build the messages for the LLM analysis call.
    Args:
        symbol: Ticker symbol.
        indicators: Output from compute_all_indicators().
        recent_candles: Last 20-30 OHLCV candles for context.
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
    if indicators.get("stochastic", {}).get("k") is not None:
        stoch = indicators["stochastic"]
        ind_lines.append(f"Stochastic: %K={stoch['k']} / %D={stoch['d']}")
    if indicators.get("macd", {}).get("macd") is not None:
        macd = indicators["macd"]
        ind_lines.append(
            f"MACD: {macd['macd']} / Signal: {macd.get('signal', 'N/A')} / Histogram: {macd.get('histogram', 'N/A')}"
        )
    if indicators.get("bollinger_bands", {}).get("middle") is not None:
        bb = indicators["bollinger_bands"]
        ind_lines.append(f"Bollinger Bands: Mid={bb['middle']:.2f} Upper={bb['upper']:.2f} Lower={bb['lower']:.2f}")
    if indicators.get("atr_14") is not None:
        ind_lines.append(f"ATR(14): ${indicators['atr_14']:.2f}")
    if indicators.get("adx_14") is not None:
        ind_lines.append(f"ADX(14): {indicators['adx_14']:.1f}")
    if indicators.get("time_series") is not None:
        ts = indicators["time_series"]
        ind_lines.append(
            "Time Series: "
            f"Stationarity={ts.get('stationarity')} / "
            f"Trend Strength={ts.get('trend_strength')} / "
            f"Seasonal Strength={ts.get('seasonal_strength')}"
        )
    if indicators.get("candlestick_patterns") is not None:
        patterns = indicators["candlestick_patterns"]
        pattern_str = ", ".join(patterns) if patterns else "None detected"
        ind_lines.append(f"Candlestick Patterns: {pattern_str}")
    indicator_summary = "\n".join(ind_lines)
    user_content = f"""Symbol: {symbol}
Interval: Daily
Date Range: {recent_candles[0].timestamp.strftime("%Y-%m-%d") if recent_candles else "N/A"} to \
{recent_candles[-1].timestamp.strftime("%Y-%m-%d") if recent_candles else "N/A"}
--- Recent Price Data ---
{price_summary}
--- Technical Indicators ---
{indicator_summary}
Analyze the above and return your trading signal as valid JSON matching the specified schema."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# Rule-based analysis (degraded mode)
# ---------------------------------------------------------------------------
def _rule_based_analysis(
    symbol: str,
    indicators: dict[str, Any],
) -> dict[str, Any]:
    """Rule-based market analysis when LLM is unavailable.
    Uses a simple voting system across multiple signals.
    Returns a dict matching MarketAnalystOutput schema.
    """
    votes: list[tuple[str, float]] = []  # (direction, confidence_weight)
    rsi = indicators.get("rsi_14")
    trend = indicators.get("trend", "neutral")
    current_price = indicators.get("current_price", 0)
    sma_20 = indicators.get("sma_20")
    sma_50 = indicators.get("sma_50")
    bb = indicators.get("bollinger_bands", {})
    volume_ratio = _volume_ratio(indicators)
    # RSI signals
    if rsi is not None:
        if rsi < 30:
            votes.append(("long", min(70, 100 - rsi)))
        elif rsi > 70:
            votes.append(("short", min(70, rsi)))
        else:
            votes.append(("flat", 30 + (50 - abs(rsi - 50))))
    # Trend signals
    if trend == "bullish":
        votes.append(("long", 60))
    elif trend == "bearish":
        votes.append(("short", 60))
    else:
        votes.append(("flat", 40))
    # SMA signals
    if sma_20 is not None and sma_50 is not None:
        if sma_20 > sma_50 and current_price > sma_20:
            votes.append(("long", 55))
        elif sma_20 < sma_50 and current_price < sma_20:
            votes.append(("short", 55))
        else:
            votes.append(("flat", 30))
    # Bollinger Band signals
    bb_mid = bb.get("middle")
    bb_upper = bb.get("upper")
    bb_lower = bb.get("lower")
    if bb_mid is not None and bb_upper is not None and bb_lower is not None:
        if current_price <= bb_lower:
            votes.append(("long", 65))  # Oversold bounce
        elif current_price >= bb_upper:
            votes.append(("short", 65))  # Overbought pullback
        elif current_price > bb_mid:
            votes.append(("long", 40))
        else:
            votes.append(("short", 40))
    # Volume confirmation
    if volume_ratio is not None and volume_ratio > 1.5:
        # High volume confirms the prevailing trend
        for i, (d, c) in enumerate(votes):
            if d != "flat":
                votes[i] = (d, min(c * 1.1, 95))
    # Tally votes
    score: dict[str, float] = {"long": 0.0, "short": 0.0, "flat": 0.0}
    for direction, weight in votes:
        score[direction] = score.get(direction, 0) + weight
    # Determine direction
    if score["long"] > score["short"] and score["long"] > score["flat"]:
        direction = "long"
        confidence = min(score["long"] / max(sum(score.values()), 1) * 100, 80)
    elif score["short"] > score["long"] and score["short"] > score["flat"]:
        direction = "short"
        confidence = min(score["short"] / max(sum(score.values()), 1) * 100, 80)
    else:
        direction = "flat"
        confidence = min(score["flat"] / max(sum(score.values()), 1) * 100, 60)
    # Extract key indicator values for the output
    output_indicators = {}
    for key in ["rsi_14", "sma_20", "sma_50", "current_price"]:
        val = indicators.get(key)
        if val is not None:
            output_indicators[key] = round(val, 4) if isinstance(val, float) else val
    macd = indicators.get("macd", {})
    if macd and macd.get("macd") is not None:
        output_indicators["macd"] = macd["macd"]
    # Build concise rationale
    signal_count = sum(1 for vote_direction, _ in votes if vote_direction == direction)
    rationale_parts = [f"Rule-based analysis ({len(votes)} signals)"]
    rationale_parts.append(f"{signal_count} {direction} signal(s)")
    if rsi is not None:
        rationale_parts.append(f"RSI={rsi:.1f}")
    if trend != "neutral":
        rationale_parts.append(f"Trend={trend}")
    rationale = " | ".join(rationale_parts)

    return {
        "confidence": round(confidence, 1),
        "direction": direction,
        "bias": trend if trend in ("bullish", "bearish") else "neutral",
        "setup": "Rule-based technicals",
        "entry_zone": f"{current_price}",
        "stop_loss": (
            f"{round(current_price * 0.95, 2)}" if direction == "long" else f"{round(current_price * 1.05, 2)}"
        ),
        "targets": [f"{round(current_price * 1.1, 2)}" if direction == "long" else f"{round(current_price * 0.9, 2)}"],
        "invalidation": "Trend reversal or MACD cross",
        "confluence": "RSI + SMA alignment",
        "indicators": output_indicators,
        "rationale": rationale,
    }


def _volume_ratio(indicators: dict[str, Any]) -> float | None:
    """Ratio of current volume to 20-period SMA of volume."""
    current_vol = indicators.get("current_volume")
    avg_vol = indicators.get("volume_sma_20")
    if current_vol is not None and avg_vol is not None and avg_vol > 0:
        return current_vol / avg_vol  # type: ignore[no-any-return]
    return None


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------
def _parse_llm_response(
    response_text: str | None,
    fallback_result: dict[str, Any],
) -> dict[str, Any]:
    """Parse LLM response text into a structured analysis result.
    If parsing fails, returns the fallback result.
    """
    if not response_text:
        fallback_result["used_fallback"] = True
        fallback_result["fallback_reason"] = "Empty response from LLM"
        return fallback_result
    text = response_text.strip()
    # Strip markdown code fences
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    data = None
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"LLM JSON parse FAILED: {e}. Raw output: {text[:500]}")
        # Try regex extraction
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                logger.warning("Recovered JSON via regex extraction")
            except json.JSONDecodeError:
                pass
    if data is None:
        logger.error("Falling back to rule-based analysis due to JSON parse failure.")
        fallback_result["used_fallback"] = True
        fallback_result["fallback_reason"] = "JSONDecodeError"
        return fallback_result
    # Validate structure
    required_fields = {"confidence", "direction", "rationale"}
    if not required_fields.issubset(data.keys()):
        logger.error(f"Missing required fields. Found keys: {list(data.keys())}")
        fallback_result["used_fallback"] = True
        fallback_result["fallback_reason"] = "Missing required fields in LLM output"
        return fallback_result
    if data.get("direction") not in ("long", "short", "flat"):
        logger.error(f"Invalid direction in LLM output: {data.get('direction')}")
        fallback_result["used_fallback"] = True
        fallback_result["fallback_reason"] = "Invalid direction in LLM output"
        return fallback_result
    confidence = float(data.get("confidence", 0))
    confidence = max(0, min(100, confidence))
    indicators = data.get("indicators", {})
    if not isinstance(indicators, dict):
        indicators = {}
    rationale = str(data.get("rationale", ""))
    return {
        "confidence": confidence,
        "direction": data["direction"],
        "bias": str(data.get("bias", "neutral")),
        "setup": str(data.get("setup", "LLM Analysis")),
        "entry_zone": str(data.get("entry_zone", "N/A")),
        "stop_loss": str(data.get("stop_loss", "N/A")),
        "targets": [str(t) for t in data.get("targets", [])],
        "invalidation": str(data.get("invalidation", "N/A")),
        "confluence": str(data.get("confluence", "N/A")),
        "indicators": {**fallback_result.get("indicators", {}), **indicators},
        "rationale": rationale or fallback_result["rationale"],
        "used_fallback": False,
        "fallback_reason": None,
    }


# ---------------------------------------------------------------------------
# MarketAnalystAgent
# ---------------------------------------------------------------------------
class MarketAnalystAgent(BaseAgent[MarketAnalystInput, MarketAnalystOutput]):
    """Market analysis agent combining technical indicators with LLM analysis.
    Two-tier analysis:
    1. Compute technical indicators from OHLCV data
    2. Send indicators + market data to LLM via ModelRouter for analysis
    3. If LLM unavailable or returns invalid output, fall back to rule-based analysis
    4. Return structured MarketAnalystOutput-compatible dict
    Usage:
        agent = MarketAnalystAgent(router=router, ingestor=ingestor)
        result = await agent.run(MarketAnalystInput(symbol="BTC-USD"))
        # result is a dict matching MarketAnalystOutput schema
    """

    agent_name: str = "market_analyst"
    input_schema: type[BaseModel] = MarketAnalystInput
    output_schema: type[BaseModel] = MarketAnalystOutput

    def __init__(
        self,
        router: ModelRouter,
        ingestor: MarketDataIngestor | None = None,
        context: AgentContext | None = None,
    ) -> None:
        super().__init__(context=context)
        self.router = router
        self.ingestor = ingestor

    async def process(self, inputs: MarketAnalystInput) -> dict[str, Any]:  # type: ignore[override]
        """Execute market analysis.
        1. Fetch/validate OHLCV data
        2. Compute technical indicators
        3. Attempt LLM analysis
        4. Fall back to rule-based if LLM unavailable
        5. Return structured result
        """
        # Step 1: Get candle data
        candles = await self._get_candles(inputs)
        if not candles:
            return {
                "confidence": 0.0,
                "direction": "flat",
                "bias": "neutral",
                "setup": "No Data",
                "entry_zone": "N/A",
                "stop_loss": "N/A",
                "targets": [],
                "invalidation": "N/A",
                "confluence": "N/A",
                "indicators": {},
                "rationale": f"No market data available for {inputs.symbol}",
            }
        # Step 2: Compute indicators
        indicators = compute_all_indicators(candles)
        # Step 3: Try LLM analysis
        llm_result = await self._llm_analysis(inputs.symbol, indicators, candles)
        # Step 4: On LLM chain exhaustion return explicit UNAVAILABLE output.
        # A rule-based fallback must never produce trade-eligible confidence —
        # consensus sees confidence 0.0 / flat and rejects (item 9, no trade).
        if llm_result is None:
            return {
                "confidence": 0.0,
                "direction": "flat",
                "bias": "neutral",
                "setup": "unavailable",
                "entry_zone": "N/A",
                "stop_loss": "N/A",
                "targets": [],
                "invalidation": "N/A",
                "confluence": "N/A",
                "indicators": {},
                "rationale": f"Market Analyst LLM chain exhausted for {inputs.symbol} — no trade.",
                "used_fallback": True,
                "fallback_reason": "llm_chain_exhausted",
            }
        return llm_result

    async def _get_candles(self, inputs: MarketAnalystInput) -> list[OHLCVData]:
        """Get OHLCV data — either pre-fetched or via ingestor."""
        if inputs.candles:
            return inputs.candles
        if self.ingestor is not None:
            try:
                request = MarketDataRequest(
                    symbol=inputs.symbol,
                    source="yahoo",
                    interval=inputs.interval,
                    limit=inputs.lookback,
                )
                result = await self.ingestor.ingest(request)
                return result.candles
            except Exception as e:
                logger.error(f"Unhandled exception: {e}", exc_info=True)
                return []
        return []

    async def _llm_analysis(
        self,
        symbol: str,
        indicators: dict[str, Any],
        candles: list[OHLCVData],
    ) -> dict[str, Any] | None:
        """Attempt LLM-based analysis. Returns None if unavailable."""
        # Build the prompt
        messages = build_analysis_prompt(symbol, indicators, candles)
        # Get this agent's model config from the registry context
        try:
            model_chain = self.context.model_preferences.get("model_chain", [])
            rpm = self.context.model_preferences.get("rpm", 10)
            temperature = self.context.model_preferences.get("temperature", 0.3)
            max_tokens = self.context.model_preferences.get("max_tokens", 1024)
        except Exception as e:
            logger.error(f"Unhandled exception: {e}", exc_info=True)
            model_chain = []
            rpm = 10
            temperature = 0.3
            max_tokens = 1024
        if not model_chain:
            return None
        # Execute via model router, enforcing JSON Schema structured output and
        # the per-model limits carried in AgentContext.model_preferences.
        router_result: RouterResult = await self.router.execute(
            model_chain=model_chain,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            rpm=rpm,
            schema_type=self.output_schema,
            breaker_threshold=self.context.model_preferences.get("breaker_threshold", 3),
            breaker_reset_seconds=self.context.model_preferences.get("breaker_reset_seconds", 300),
        )
        if router_result.fallback_used:
            primary_model = model_chain[0] if model_chain else "unknown"
            record_agent_fallback(self.agent_name, primary_model, router_result.model_used)
        if not router_result.success or router_result.degraded:
            return None
        # Parse the response
        response_text = None
        if router_result.response:
            try:
                response_text = router_result.response["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                pass
        # Get fallback for this symbol
        fallback = _rule_based_analysis(symbol, indicators)
        return _parse_llm_response(response_text, fallback)
