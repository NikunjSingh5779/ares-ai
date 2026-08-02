"""Consensus Engine — deterministic signal validation gate.

Evaluates outputs from Market Analyst and Quant agents against
confidence thresholds and direction agreement. Optionally considers
Vision agent's chart-pattern analysis as an advisory nudge.

Per CLAUDE.md CONSENSUS ENGINE:
- Market Analyst confidence > 80%
- AND Quant confidence > 80%
- AND directions agree (neither flat)
- Otherwise reject the trade
- Vision is advisory: when available and confident, its chart-pattern
  agreement can nudge composite_confidence by a small bounded amount
  (±3%), but it can never flip an approval decision on its own.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

REQUIRED_CONFIDENCE: float = 80.0
"""Minimum confidence required from both agents to approve a trade."""

VISION_CONFIDENCE_THRESHOLD: float = 60.0
"""Minimum vision confidence to consider its pattern analysis as a nudge."""

VISION_NUDGE_AMOUNT: float = 3.0
"""Bounded confidence adjustment when vision agrees/disagrees with MA/quant direction."""


class ConsensusInput(BaseModel):
    """Input for the Consensus Engine.

    Receives the structured outputs from Market Analyst and Quant agents,
    plus an optional advisory Vision output.
    """

    symbol: str = Field(..., description="Ticker symbol")
    market_analyst_output: dict[str, Any] | None = Field(
        default=None,
        description="Output from MarketAnalystAgent",
    )
    quant_output: dict[str, Any] | None = Field(
        default=None,
        description="Output from QuantAgent",
    )
    vision_output: dict[str, Any] | None = Field(
        default=None,
        description="Advisory output from VisionAgent (optional, non-blocking)",
    )


def _vision_nudge(
    vision_output: dict[str, Any] | None,
    ma_direction: str,
) -> float:
    """Compute a small bounded confidence adjustment from vision analysis.

    Returns a float in [-VISION_NUDGE_AMOUNT, VISION_NUDGE_AMOUNT] that is
    added to composite_confidence. Positive when vision agrees, negative
    when it disagrees, zero when vision is unavailable or low-confidence.

    This is intentionally bounded so vision can never flip an approval
    decision on its own — it only slightly shifts the confidence signal.
    """
    if not vision_output:
        return 0.0

    available = vision_output.get("available", False)
    confidence = float(vision_output.get("confidence", 0))
    chart_pattern: str | None = vision_output.get("chart_pattern")

    if not available or confidence < VISION_CONFIDENCE_THRESHOLD or not chart_pattern:
        return 0.0

    # Map chart pattern to a coarse direction
    pattern_to_direction = {
        "uptrend": "long",
        "downtrend": "short",
        "consolidation": "flat",
    }
    vision_direction = pattern_to_direction.get(chart_pattern.lower(), None)
    if vision_direction is None or vision_direction == "flat":
        return 0.0

    if vision_direction == ma_direction:
        return VISION_NUDGE_AMOUNT  # agree → small positive nudge
    return -VISION_NUDGE_AMOUNT  # disagree → small negative nudge


class ConsensusEngine:
    """Deterministic consensus evaluation between Market Analyst and Quant.

    This is a rule-based validation layer, not an LLM agent.
    It enforces the confidence thresholds and direction agreement
    required by the CONSENSUS ENGINE section of CLAUDE.md.

    Vision output is advisory: it provides a small bounded nudge to
    composite_confidence but never overrides an approval decision.
    """

    @staticmethod
    def evaluate(
        symbol: str,
        market_analyst_output: dict[str, Any] | None,
        quant_output: dict[str, Any] | None,
        vision_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Evaluate consensus and return a ConsensusOutput-compatible dict.

        Args:
            symbol: Ticker symbol.
            market_analyst_output: MarketAnalystAgent output dict, or None.
            quant_output: QuantAgent output dict, or None.
            vision_output: Advisory VisionAgent output dict, or None.
                When None or unavailable, behaviour is byte-for-byte
                identical to calling without this parameter.

        Returns:
            Dict matching ConsensusOutput schema with approved flag,
            composite_confidence, agreement_metrics, and rationale.
        """
        # Check that both agents produced output
        if market_analyst_output is None or quant_output is None:
            missing = []
            if market_analyst_output is None:
                missing.append("Market Analyst")
            if quant_output is None:
                missing.append("Quant")
            return {
                "approved": False,
                "composite_confidence": 0.0,
                "agreement_metrics": {
                    "ma_confidence": 0.0,
                    "quant_confidence": 0.0,
                    "ma_direction": "unknown",
                    "quant_direction": "unknown",
                    "directions_agree": False,
                    "vision_available": bool(vision_output.get("available")) if vision_output else False,
                    "vision_agreement": None,
                },
                "rationale": (f"Consensus rejected: {', '.join(missing)} agent(s) produced no output for {symbol}"),
            }

        # Extract fields
        ma_confidence = float(market_analyst_output.get("confidence", 0))
        quant_confidence = float(quant_output.get("confidence", 0))
        ma_direction = str(market_analyst_output.get("direction", "flat"))
        quant_direction = str(quant_output.get("direction", "flat"))

        # Check confidence thresholds
        both_confident = ma_confidence >= REQUIRED_CONFIDENCE and quant_confidence >= REQUIRED_CONFIDENCE

        # Check direction agreement (both must agree and neither is flat)
        directions_agree = ma_direction == quant_direction and ma_direction in ("long", "short")

        approved = both_confident and directions_agree
        composite_confidence = (ma_confidence + quant_confidence) / 2.0

        # Vision advisory nudge — only when the base consensus is approved.
        # Vision should never flip an approval decision on its own.
        nudge = _vision_nudge(vision_output, ma_direction) if approved else 0.0
        vision_agreement: bool | None = None
        if nudge > 0:
            vision_agreement = True
        elif nudge < 0:
            vision_agreement = False

        if nudge != 0:
            composite_confidence = max(0.0, min(100.0, composite_confidence + nudge))
            composite_confidence = round(composite_confidence, 1)

        # Build rationale
        if not both_confident:
            rationale = (
                f"Consensus rejected: confidence thresholds not met. "
                f"Market Analyst: {ma_confidence:.1f}% (need ≥ {REQUIRED_CONFIDENCE:.0f}%), "
                f"Quant: {quant_confidence:.1f}%"
            )
        elif not directions_agree:
            rationale = (
                f"Consensus rejected: direction mismatch. Market Analyst: {ma_direction}, Quant: {quant_direction}"
            )
        else:
            rationale = (
                f"Consensus approved for {symbol}. "
                f"Both agents agree on {ma_direction} with "
                f"composite confidence {composite_confidence:.1f}%"
            )

        # Add vision advisory note to rationale when a nudge was applied
        if nudge > 0:
            rationale += f" | Vision confirms {ma_direction} (chart pattern)"
        elif nudge < 0:
            rationale += f" | Vision diverges from {ma_direction} (chart pattern conflicts)"

        return {
            "approved": approved,
            "composite_confidence": round(composite_confidence, 1),
            "agreement_metrics": {
                "ma_confidence": ma_confidence,
                "quant_confidence": quant_confidence,
                "ma_direction": ma_direction,
                "quant_direction": quant_direction,
                "directions_agree": directions_agree,
                "vision_available": bool(vision_output.get("available")) if vision_output else False,
                "vision_agreement": vision_agreement,
            },
            "rationale": rationale,
        }
