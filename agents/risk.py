"""Risk Agent — portfolio risk assessment and trade approval.

Evaluates trade signals against risk parameters (position sizing,
drawdown limits, portfolio exposure) and approves or rejects.

Follows the same BaseAgent pattern as MarketAnalystAgent and QuantAgent
with LLM analysis + rule-based fallback.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from agents.base import AgentContext, BaseAgent
from agents.indicators import compute_all_indicators, compute_atr, _extract_closes
from agents.router import ModelRouter, RouterResult
from backend.data.ingestor import MarketDataIngestor
from backend.data.models import OHLCVData


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_POSITION_SIZE_PCT: float = 2.0
"""Maximum position size as percentage of portfolio value (2% rule)."""

MAX_RISK_SCORE: float = 70.0
"""Maximum risk score allowed for approval (0-100)."""


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class RiskInput(BaseModel):
    """Input for the Risk Agent.

    Receives pre-fetched candles or enough info to fetch them,
    plus the outputs from upstream agents for context.
    """

    symbol: str = Field(..., description="Ticker symbol")
    interval: str = Field(default="1d", description="Candle interval")
    lookback: int = Field(default=100, description="Number of candles")
    candles: list[OHLCVData] | None = Field(
        default=None,
        description="Pre-fetched OHLCV data",
    )
    portfolio_value: float = Field(
        default=100000.0,
        description="Current portfolio value in USD",
    )
    current_positions: dict[str, Any] = Field(
        default_factory=dict,
        description="Current open positions",
    )
    market_analyst_output: dict[str, Any] | None = Field(
        default=None,
        description="MarketAnalystAgent output for context",
    )
    quant_output: dict[str, Any] | None = Field(
        default=None,
        description="QuantAgent output for context",
    )
    consensus_output: dict[str, Any] | None = Field(
        default=None,
        description="ConsensusEngine output",
    )


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

RISK_SYSTEM_PROMPT = """You are the Risk Agent in the ARES AI trading system.

Your role: Assess the risk of the proposed trade signal and decide whether
to approve or reject it. You are the final gate before execution.

Risk assessment criteria:
1. Position size: Should not exceed 2% of portfolio value per trade.
2. Stop loss: Should be placed at a level that limits loss to acceptable range.
3. Portfolio exposure: Consider existing positions and overall market exposure.
4. Market volatility: Higher volatility (ATR) requires wider stops and smaller size.
5. Signal strength: Consider the confidence from upstream agents.

Return ONLY valid JSON matching this schema:
{{
  "approved": <bool, true to approve trade, false to reject>,
  "max_position_size": <float | null, max position size in units>,
  "stop_loss": <float | null, stop loss price level>,
  "risk_score": <float 0-100, overall risk assessment>,
  "reasons": [<string, ...>, list of reasons for the decision>,
  "rationale": "<string explaining your risk assessment>"
}}"""


def build_risk_prompt(
    symbol: str,
    indicators: dict[str, Any],
    market_analyst_output: dict[str, Any] | None,
    quant_output: dict[str, Any] | None,
    consensus_output: dict[str, Any] | None,
    portfolio_value: float,
) -> list[dict[str, str]]:
    """Build messages for the LLM risk assessment call.

    Args:
        symbol: Ticker symbol.
        indicators: Output from compute_all_indicators().
        market_analyst_output: MarketAnalystAgent output, or None.
        quant_output: QuantAgent output, or None.
        consensus_output: ConsensusEngine output, or None.
        portfolio_value: Current portfolio value.

    Returns:
        List of {"role": ..., "content": ...} dicts for the LLM call.
    """
    context_parts = [f"Symbol: {symbol}", f"Portfolio Value: ${portfolio_value:,.2f}"]

    # Market context from indicators
    price = indicators.get("current_price", "N/A")
    atr = indicators.get("atr_14")
    bb = indicators.get("bollinger_bands", {})
    context_parts.append(f"Current Price: ${price}" if price != "N/A" else "Current Price: N/A")
    if atr is not None:
        context_parts.append(f"ATR(14): ${atr:.2f}")
    if bb.get("middle"):
        context_parts.append(f"Bollinger Bands: Mid={bb['middle']:.2f} Upper={bb['upper']:.2f} Lower={bb['lower']:.2f}")

    # Upstream agent signals
    if market_analyst_output:
        context_parts.append(
            f"\nMarket Analyst Signal:\n"
            f"  Direction: {market_analyst_output.get('direction', 'N/A')}\n"
            f"  Confidence: {market_analyst_output.get('confidence', 'N/A')}%\n"
            f"  Rationale: {market_analyst_output.get('rationale', 'N/A')}"
        )
    if quant_output:
        context_parts.append(
            f"\nQuant Signal:\n"
            f"  Direction: {quant_output.get('direction', 'N/A')}\n"
            f"  Confidence: {quant_output.get('confidence', 'N/A')}%\n"
            f"  Strategy: {quant_output.get('strategy_name', 'N/A')}\n"
            f"  Expected Return: {quant_output.get('expected_return', 'N/A')}%\n"
            f"  Rationale: {quant_output.get('rationale', 'N/A')}"
        )
    if consensus_output:
        context_parts.append(
            f"\nConsensus Assessment:\n"
            f"  Approved: {consensus_output.get('approved', False)}\n"
            f"  Composite Confidence: {consensus_output.get('composite_confidence', 'N/A')}%\n"
            f"  Rationale: {consensus_output.get('rationale', 'N/A')}"
        )

    context_parts.append(
        "\nAssess the risk of this trade and return your decision "
        "as valid JSON matching the specified schema."
    )

    return [
        {"role": "system", "content": RISK_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(context_parts)},
    ]


# ---------------------------------------------------------------------------
# Rule-based risk assessment (degraded mode)
# ---------------------------------------------------------------------------

def _rule_based_risk(
    symbol: str,
    indicators: dict[str, Any],
    market_analyst_output: dict[str, Any] | None = None,
    quant_output: dict[str, Any] | None = None,
    consensus_output: dict[str, Any] | None = None,
    portfolio_value: float = 100000.0,
) -> dict[str, Any]:
    """Rule-based risk assessment when LLM is unavailable.

    Uses conservative defaults: 2% position sizing, ATR-based stop loss,
    and rejects if consensus is not approved.
    """
    if portfolio_value <= 0:
        portfolio_value = 100000.0

    price = indicators.get("current_price", 0)
    atr = indicators.get("atr_14")

    # Check consensus approval
    consensus_approved = False
    if consensus_output:
        consensus_approved = bool(consensus_output.get("approved", False))
    elif market_analyst_output and quant_output:
        # Fallback: check confidence thresholds directly
        ma_conf = float(market_analyst_output.get("confidence", 0))
        quant_conf = float(quant_output.get("confidence", 0))
        ma_dir = str(market_analyst_output.get("direction", "flat"))
        quant_dir = str(quant_output.get("direction", "flat"))
        consensus_approved = (
            ma_conf >= 80.0
            and quant_conf >= 80.0
            and ma_dir == quant_dir
            and ma_dir in ("long", "short")
        )

    if not consensus_approved:
        return {
            "approved": False,
            "max_position_size": None,
            "stop_loss": None,
            "risk_score": 100.0,
            "reasons": ["Consensus not approved"],
            "rationale": f"Risk rejected for {symbol}: upstream signals did not pass consensus",
        }

    # Calculate position sizing (2% rule)
    direction = market_analyst_output.get("direction", "flat") if market_analyst_output else "flat"
    max_position_value = portfolio_value * (MAX_POSITION_SIZE_PCT / 100.0)

    max_position_size = None
    stop_loss = None
    if price and price > 0:
        max_position_size = round(max_position_value / price, 4)

        # Stop loss based on ATR (2x ATR away from entry)
        if atr and atr > 0:
            if direction == "long":
                stop_loss = round(price - atr * 2.0, 2)
            else:
                stop_loss = round(price + atr * 2.0, 2)

    # Calculate risk score
    risk_score = _compute_risk_score(indicators, portfolio_value)

    approved = risk_score <= MAX_RISK_SCORE

    reasons = []
    if approved:
        reasons.append(f"Position size within {MAX_POSITION_SIZE_PCT}% limit")
        reasons.append(f"Risk score {risk_score:.1f} within acceptable range")
    else:
        reasons.append(f"Risk score {risk_score:.1f} exceeds maximum {MAX_RISK_SCORE:.0f}")
        if atr:
            reasons.append(f"Volatility elevated (ATR=${atr:.2f})")

    return {
        "approved": approved,
        "max_position_size": max_position_size,
        "stop_loss": stop_loss,
        "risk_score": round(risk_score, 1),
        "reasons": reasons,
        "rationale": (
            f"Risk {'approved' if approved else 'rejected'} for {symbol}. "
            f"Portfolio=${portfolio_value:,.0f}, "
            f"Risk score={risk_score:.1f}/100, "
            f"Max position={max_position_size} units at ${price:.2f}"
        ),
    }


def _compute_risk_score(
    indicators: dict[str, Any],
    portfolio_value: float,
) -> float:
    """Compute a risk score from 0 (low risk) to 100 (high risk).

    Factors: ATR volatility, RSI extreme, trend weakness, portfolio exposure.
    """
    score = 30.0  # base score

    # ATR volatility contribution
    atr = indicators.get("atr_14")
    price = indicators.get("current_price", 0)
    if atr and price > 0:
        atr_pct = atr / price * 100
        if atr_pct > 5.0:
            score += 30  # very high volatility
        elif atr_pct > 3.0:
            score += 20
        elif atr_pct > 1.5:
            score += 10

    # RSI extreme contribution
    rsi = indicators.get("rsi_14")
    if rsi is not None:
        if rsi > 80 or rsi < 20:
            score += 15  # extreme
        elif rsi > 70 or rsi < 30:
            score += 8  # borderline

    # Trend weakness
    trend = indicators.get("trend")
    if trend == "neutral":
        score += 10

    # Portfolio contribution (conservative scaling)
    if portfolio_value < 10000:
        score += 10  # small account = higher risk per trade

    return min(score, 100.0)


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _parse_risk_response(
    response_text: str | None,
    fallback_result: dict[str, Any],
) -> dict[str, Any]:
    """Parse LLM response text into a RiskOutput-compatible dict.

    If parsing fails, returns the fallback result.
    """
    if not response_text:
        return fallback_result

    text = response_text.strip()
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

    required = {"approved", "risk_score", "rationale"}
    if not required.issubset(data.keys()):
        return fallback_result

    approved = bool(data.get("approved", False))
    risk_score = max(0.0, min(100.0, float(data.get("risk_score", 0))))

    max_position_size = data.get("max_position_size")
    if max_position_size is not None:
        try:
            max_position_size = float(max_position_size)
        except (ValueError, TypeError):
            max_position_size = fallback_result.get("max_position_size")

    stop_loss = data.get("stop_loss")
    if stop_loss is not None:
        try:
            stop_loss = float(stop_loss)
        except (ValueError, TypeError):
            stop_loss = fallback_result.get("stop_loss")

    reasons = data.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = fallback_result.get("reasons", [])

    rationale = str(data.get("rationale", "")) or fallback_result.get("rationale", "")

    return {
        "approved": approved,
        "max_position_size": max_position_size,
        "stop_loss": stop_loss,
        "risk_score": risk_score,
        "reasons": reasons,
        "rationale": rationale,
    }


# ---------------------------------------------------------------------------
# RiskAgent
# ---------------------------------------------------------------------------

class RiskAgent(BaseAgent[RiskInput, dict]):
    """Risk assessment agent for trade approval.

    Two-tier analysis:
    1. Compute indicators from OHLCV data for volatility context
    2. Send portfolio context + agent signals to LLM via ModelRouter
    3. If LLM unavailable, fall back to rule-based risk assessment
    4. Return structured RiskOutput-compatible dict

    Usage:
        agent = RiskAgent(router=router)
        result = await agent.run(RiskInput(symbol="BTC-USD", ...))
    """

    agent_name: str = "risk"
    input_schema: type[BaseModel] = RiskInput

    def __init__(
        self,
        router: ModelRouter,
        ingestor: MarketDataIngestor | None = None,
        context: AgentContext | None = None,
    ) -> None:
        super().__init__(context=context)
        self.router = router
        self.ingestor = ingestor

    async def process(self, inputs: RiskInput) -> dict[str, Any]:
        """Execute risk assessment.

        1. Get OHLCV data for volatility context
        2. Compute indicators
        3. Attempt LLM risk assessment
        4. Fall back to rule-based if LLM unavailable
        5. Return structured result
        """
        # Step 1: Get candle data
        candles = await self._get_candles(inputs)
        indicators = compute_all_indicators(candles) if candles else {}

        # Step 2: Try LLM analysis
        llm_result = await self._llm_risk(
            inputs.symbol, indicators, inputs,
        )

        # Step 3: Fall back to rule-based if needed
        if llm_result is None:
            llm_result = _rule_based_risk(
                inputs.symbol, indicators,
                market_analyst_output=inputs.market_analyst_output,
                quant_output=inputs.quant_output,
                consensus_output=inputs.consensus_output,
                portfolio_value=inputs.portfolio_value,
            )

        return llm_result

    async def _get_candles(self, inputs: RiskInput) -> list[OHLCVData]:
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

    async def _llm_risk(
        self,
        symbol: str,
        indicators: dict[str, Any],
        inputs: RiskInput,
    ) -> dict[str, Any] | None:
        """Attempt LLM-based risk assessment. Returns None if unavailable."""
        messages = build_risk_prompt(
            symbol, indicators,
            market_analyst_output=inputs.market_analyst_output,
            quant_output=inputs.quant_output,
            consensus_output=inputs.consensus_output,
            portfolio_value=inputs.portfolio_value,
        )

        try:
            model_chain = self.context.model_preferences.get("model_chain", [])
            rpm = self.context.model_preferences.get("rpm", 10)
            temperature = self.context.model_preferences.get("temperature", 0.3)
            max_tokens = self.context.model_preferences.get("max_tokens", 1024)
        except Exception:
            model_chain = []

        if not model_chain:
            return None

        router_result: RouterResult = await self.router.execute(
            model_chain=model_chain,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            rpm=rpm,
        )

        if not router_result.success or router_result.degraded:
            return None

        response_text = None
        if router_result.response:
            try:
                response_text = router_result.response["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                pass

        fallback = _rule_based_risk(
            symbol, indicators,
            market_analyst_output=inputs.market_analyst_output,
            quant_output=inputs.quant_output,
            consensus_output=inputs.consensus_output,
            portfolio_value=inputs.portfolio_value,
        )
        return _parse_risk_response(response_text, fallback)
