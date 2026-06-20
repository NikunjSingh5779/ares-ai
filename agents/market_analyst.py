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
   {{
     "confidence": <float 0-100, how confident you are in this signal>,
     "direction": <"long" | "short" | "flat">,
     "indicators": {{ <indicator_name>: <value>, ... }},
     "rationale": "<string explaining your reasoning>"
   }}
3. confidence < 50 means you're uncertain — prefer "flat" in that case.
4. Consider: trend, momentum (RSI), volatility (Bollinger Bands), volume.
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
    if indicators.get("macd", {}).get("macd") is not None:
        macd = indicators["macd"]
        ind_lines.append(f"MACD: {macd['macd']} / Signal: {macd.get('signal', 'N/A')} / Histogram: {macd.get('histogram', 'N/A')}")
    if indicators.get("bollinger_bands", {}).get("middle") is not None:
        bb = indicators["bollinger_bands"]
        ind_lines.append(f"Bollinger Bands: Mid={bb['middle']:.2f} Upper={bb['upper']:.2f} Lower={bb['lower']:.2f}")
    if indicators.get("atr_14") is not None:
        ind_lines.append(f"ATR(14): ${indicators['atr_14']:.2f}")

    indicator_summary = "\n".join(ind_lines)

    user_content = f"""Symbol: {symbol}
Interval: Daily
Date Range: {recent_candles[0].timestamp.strftime('%Y-%m-%d') if recent_candles else 'N/A'} to {recent_candles[-1].timestamp.strftime('%Y-%m-%d') if recent_candles else 'N/A'}

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
    signal_reasons = [d for d, w in votes if d == direction]
    rationale_parts = [f"Rule-based analysis ({len(votes)} signals)"]
    if rsi is not None:
        rationale_parts.append(f"RSI={rsi:.1f}")
    if trend != "neutral":
        rationale_parts.append(f"Trend={trend}")
    rationale = " | ".join(rationale_parts)

    return {
        "confidence": round(confidence, 1),
        "direction": direction,
        "indicators": output_indicators,
        "rationale": rationale,
    }


def _volume_ratio(indicators: dict[str, Any]) -> float | None:
    """Ratio of current volume to 20-period SMA of volume."""
    current_vol = indicators.get("current_volume")
    avg_vol = indicators.get("volume_sma_20")
    if current_vol is not None and avg_vol is not None and avg_vol > 0:
        return current_vol / avg_vol
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
        return fallback_result

    text = response_text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return fallback_result

    # Validate structure
    required_fields = {"confidence", "direction", "rationale"}
    if not required_fields.issubset(data.keys()):
        return fallback_result

    if data.get("direction") not in ("long", "short", "flat"):
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
        "indicators": {**fallback_result.get("indicators", {}), **indicators},
        "rationale": rationale or fallback_result["rationale"],
    }


# ---------------------------------------------------------------------------
# MarketAnalystAgent
# ---------------------------------------------------------------------------

class MarketAnalystAgent(BaseAgent[MarketAnalystInput, dict]):
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

    def __init__(
        self,
        router: ModelRouter,
        ingestor: MarketDataIngestor | None = None,
        context: AgentContext | None = None,
    ) -> None:
        super().__init__(context=context)
        self.router = router
        self.ingestor = ingestor

    async def process(self, inputs: MarketAnalystInput) -> dict[str, Any]:
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
                "indicators": {},
                "rationale": f"No market data available for {inputs.symbol}",
            }

        # Step 2: Compute indicators
        indicators = compute_all_indicators(candles)

        # Step 3: Try LLM analysis
        llm_result = await self._llm_analysis(inputs.symbol, indicators, candles)

        # Step 4: Fall back to rule-based if needed
        if llm_result is None:
            llm_result = _rule_based_analysis(inputs.symbol, indicators)

        return llm_result

    async def _get_candles(self, inputs: MarketAnalystInput) -> list[OHLCVData]:
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

        # Get fallback for this symbol
        fallback = _rule_based_analysis(symbol, indicators)

        return _parse_llm_response(response_text, fallback)
