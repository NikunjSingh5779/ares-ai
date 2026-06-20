"""Consensus Engine — deterministic signal validation gate.

Evaluates outputs from Market Analyst and Quant agents against
confidence thresholds and direction agreement. No LLM involvement.

Per CLAUDE.md CONSENSUS ENGINE:
- Market Analyst confidence > 80%
- AND Quant confidence > 80%
- AND directions agree (neither flat)
- Otherwise reject the trade
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


REQUIRED_CONFIDENCE: float = 80.0
"""Minimum confidence required from both agents to approve a trade."""


class ConsensusInput(BaseModel):
    """Input for the Consensus Engine.

    Receives the structured outputs from Market Analyst and Quant agents.
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


class ConsensusEngine:
    """Deterministic consensus evaluation between Market Analyst and Quant.

    This is a rule-based validation layer, not an LLM agent.
    It enforces the confidence thresholds and direction agreement
    required by the CONSENSUS ENGINE section of CLAUDE.md.
    """

    @staticmethod
    def evaluate(
        symbol: str,
        market_analyst_output: dict[str, Any] | None,
        quant_output: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Evaluate consensus and return a ConsensusOutput-compatible dict.

        Args:
            symbol: Ticker symbol.
            market_analyst_output: MarketAnalystAgent output dict, or None.
            quant_output: QuantAgent output dict, or None.

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
                },
                "rationale": (
                    f"Consensus rejected: {', '.join(missing)} agent(s) "
                    f"produced no output for {symbol}"
                ),
            }

        # Extract fields
        ma_confidence = float(market_analyst_output.get("confidence", 0))
        quant_confidence = float(quant_output.get("confidence", 0))
        ma_direction = str(market_analyst_output.get("direction", "flat"))
        quant_direction = str(quant_output.get("direction", "flat"))

        # Check confidence thresholds
        both_confident = (
            ma_confidence >= REQUIRED_CONFIDENCE
            and quant_confidence >= REQUIRED_CONFIDENCE
        )

        # Check direction agreement (both must agree and neither is flat)
        directions_agree = (
            ma_direction == quant_direction
            and ma_direction in ("long", "short")
        )

        approved = both_confident and directions_agree
        composite_confidence = (ma_confidence + quant_confidence) / 2.0

        # Build rationale
        if not both_confident:
            rationale = (
                f"Consensus rejected: confidence thresholds not met. "
                f"Market Analyst: {ma_confidence:.1f}% (need ≥ {REQUIRED_CONFIDENCE:.0f}%), "
                f"Quant: {quant_confidence:.1f}%"
            )
        elif not directions_agree:
            rationale = (
                f"Consensus rejected: direction mismatch. "
                f"Market Analyst: {ma_direction}, Quant: {quant_direction}"
            )
        else:
            rationale = (
                f"Consensus approved for {symbol}. "
                f"Both agents agree on {ma_direction} with "
                f"composite confidence {composite_confidence:.1f}%"
            )

        return {
            "approved": approved,
            "composite_confidence": round(composite_confidence, 1),
            "agreement_metrics": {
                "ma_confidence": ma_confidence,
                "quant_confidence": quant_confidence,
                "ma_direction": ma_direction,
                "quant_direction": quant_direction,
                "directions_agree": directions_agree,
            },
            "rationale": rationale,
        }
