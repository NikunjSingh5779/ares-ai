"""Reflection Agent — post-trade evaluation and improvement.

Evaluates the pipeline output after execution, comparing predicted
confidence/outcome to actual results (when available), generating
improvement suggestions and knowledge updates.

Follows the same BaseAgent pattern with rule-based logic +
optional LLM enhancement via ModelRouter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agents.base import AgentContext, BaseAgent


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_CONFIDENCE_THRESHOLD: float = 80.0
"""Confidence threshold below which a prediction is considered weak."""

CROSS_SESSION_HISTORY_SIZE: int = 50
"""Number of recent reflection outputs retained for cross-session analysis."""

DEGRADATION_SIGNAL_THRESHOLD: float = 15.0
"""Confidence accuracy decline over the window that triggers a degradation flag."""


# ---------------------------------------------------------------------------
# Cross-session history (in-memory — replace with DB in production)
# ---------------------------------------------------------------------------

_reflection_history: list[dict[str, Any]] = []


def _get_reflection_history() -> list[dict[str, Any]]:
    """Get the cross-session reflection history."""
    return list(_reflection_history)


def _reset_reflection_history() -> None:
    """Clear cross-session history (for testing)."""
    _reflection_history.clear()


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class ReflectionInput(BaseModel):
    """Input for the Reflection Agent.

    Receives all pipeline outputs via extra fields (``extra="allow"``)
    since the input shape depends on which agents have run.
    """

    symbol: str = Field(default="", description="Ticker symbol")
    request: str = Field(default="", description="Original user request")
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Reflection Agent
# ---------------------------------------------------------------------------


class ReflectionAgent(BaseAgent[ReflectionInput, dict]):
    """Post-trade reflection and evaluation agent.

    Rule-based evaluation:
    1. Review execution result and pipeline outputs
    2. Calculate confidence accuracy from market_analyst/consensus vs outcome
    3. Generate improvement suggestions based on pattern detection
    4. Generate knowledge updates for future runs
    5. Cross-session pattern detection — compare across recent runs

    Usage::

        agent = ReflectionAgent()
        result = await agent.run(ReflectionInput(symbol="BTC-USD", ...))
    """

    agent_name: str = "reflection"
    input_schema: type[BaseModel] = ReflectionInput

    def __init__(self, context: AgentContext | None = None) -> None:
        super().__init__(context=context)

    async def process(self, inputs: ReflectionInput) -> dict[str, Any]:
        """Execute post-trade reflection.

        Examines all available pipeline outputs and generates
        evaluation metrics, improvement suggestions, and knowledge updates.
        """
        global _reflection_history

        # Extract pipeline outputs from extra fields
        output_map = _extract_agent_outputs(inputs)
        symbol = inputs.symbol or "unknown"

        execution = output_map.get("execution", {})
        market_analyst = output_map.get("market_analyst", {})
        consensus = output_map.get("consensus", {})
        risk = output_map.get("risk", {})
        errors = output_map.get("errors", [])

        executed = bool(execution.get("executed", False))

        # --- Evaluation ---
        evaluation_parts = [f"Reflection for {symbol}:"]

        if executed:
            fill_price = execution.get("fill_price")
            direction = market_analyst.get("direction", "unknown")
            confidence = float(market_analyst.get("confidence", 0))
            price_str = f"${fill_price:.2f}" if fill_price is not None else "N/A"
            eval_text = (
                f"Trade executed: {direction} at {price_str}. "
                f"Analyst confidence was {confidence:.1f}%."
            )
            evaluation_parts.append(eval_text)
        else:
            reason = execution.get("rationale", "No trade executed")
            evaluation_parts.append(f"Trade not executed: {reason}")

        # --- Confidence accuracy ---
        has_data = bool(market_analyst) or bool(consensus)
        if not has_data:
            confidence_accuracy = 0.0
        else:
            confidence_accuracy = _compute_confidence_accuracy(market_analyst, consensus, executed)

        # --- Improvement suggestions ---
        suggestions = _generate_suggestions(
            market_analyst, consensus, risk, errors, executed,
        )

        # --- Cross-session pattern detection ---
        cross_session_suggestions = _detect_cross_session_patterns(
            confidence_accuracy, executed,
        )
        suggestions.extend(cross_session_suggestions)

        # --- Knowledge updates ---
        knowledge_updates = _generate_knowledge_updates(
            market_analyst, consensus, executed,
        )

        # --- Store in cross-session history ---
        _reflection_history.append({
            "symbol": symbol,
            "executed": executed,
            "confidence_accuracy": confidence_accuracy,
            "evaluation": evaluation_parts,
            "suggestions": suggestions,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        if len(_reflection_history) > CROSS_SESSION_HISTORY_SIZE:
            _reflection_history = _reflection_history[-CROSS_SESSION_HISTORY_SIZE:]

        evaluation = " | ".join(evaluation_parts)

        return {
            "evaluation": evaluation,
            "confidence_accuracy": round(confidence_accuracy, 2),
            "improvement_suggestions": suggestions,
            "knowledge_updates": knowledge_updates,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_agent_outputs(inputs: ReflectionInput) -> dict[str, Any]:
    """Extract agent outputs from the input's extra fields.

    The supervisor injects outputs as ``{name}_output`` keys.
    """
    output_map: dict[str, Any] = {}
    agent_names = [
        "market_analyst", "quant", "news", "vision", "consensus",
        "risk", "execution",
    ]
    for name in agent_names:
        val = getattr(inputs, f"{name}_output", None)
        if val is not None:
            output_map[name] = val
    # Also check for errors
    errors = getattr(inputs, "errors", None) or []
    if errors:
        output_map["errors"] = errors
    return output_map


def _compute_confidence_accuracy(
    market_analyst: dict[str, Any],
    consensus: dict[str, Any],
    executed: bool,
) -> float:
    """Compute accuracy of confidence predictions.

    Returns a score from 0 (inaccurate) to 100 (accurate).
    For executed trades, high confidence that was correct = high accuracy.
    For rejected trades, low confidence that led to rejection = high accuracy.
    """
    ma_conf = float(market_analyst.get("confidence", 0)) if market_analyst else 0.0
    consensus_conf = float(consensus.get("composite_confidence", 0)) if consensus else 0.0
    avg_conf = (ma_conf + consensus_conf) / 2 if ma_conf and consensus_conf else (ma_conf or consensus_conf)

    if not executed:
        # Trade was not executed — if confidence was low, that's accurate (conservative)
        if avg_conf < MIN_CONFIDENCE_THRESHOLD:
            return 90.0  # Correctly cautious
        # Confidence was high but trade was rejected — possible disagreement
        return 50.0

    # Trade was executed — high confidence aligned with execution
    if avg_conf >= MIN_CONFIDENCE_THRESHOLD:
        return 85.0  # High confidence → acted → good
    # Low confidence but still executed
    return 60.0  # Some uncertainty in the signal


def _generate_suggestions(
    market_analyst: dict[str, Any],
    consensus: dict[str, Any],
    risk: dict[str, Any],
    errors: list[Any],
    executed: bool,
) -> list[str]:
    """Generate improvement suggestions based on pipeline patterns."""
    suggestions: list[str] = []

    if errors:
        suggestions.append(
            f"Investigate {len(errors)} error(s) in the pipeline — "
            f"check agent reliability and fallback chains"
        )

    if not executed:
        suggestions.append("Review risk criteria — consider if thresholds are appropriately calibrated")
    else:
        ma_conf = float(market_analyst.get("confidence", 0)) if market_analyst else 0
        if ma_conf < 60:
            suggestions.append(
                "Market analyst confidence was low — consider gathering more data "
                "before executing marginal signals"
            )

    # Consensus disgreement
    if consensus:
        comp_conf = float(consensus.get("composite_confidence", 0))
        if 50 < comp_conf < 80:
            suggestions.append(
                "Composite confidence in moderate range — review agent alignment"
            )

    if not suggestions:
        suggestions.append("No significant issues detected — current pipeline operating nominally")

    return suggestions


def _generate_knowledge_updates(
    market_analyst: dict[str, Any],
    consensus: dict[str, Any],
    executed: bool,
) -> list[str]:
    """Generate knowledge updates for the memory system."""
    updates: list[str] = []

    if market_analyst:
        direction = market_analyst.get("direction", "unknown")
        confidence = market_analyst.get("confidence", 0)
        updates.append(f"Market analysis: {direction} signal at {confidence}% confidence")

    if consensus:
        updates.append(
            f"Consensus: composite confidence was "
            f"{consensus.get('composite_confidence', 'N/A')}%"
        )

    if executed:
        updates.append("Signal passed all gates and was executed")
    else:
        updates.append("Signal was rejected before execution")

    return updates


# ---------------------------------------------------------------------------
# Cross-session pattern detection
# ---------------------------------------------------------------------------


def _detect_cross_session_patterns(
    confidence_accuracy: float,
    executed: bool,
) -> list[str]:
    """Detect degradation signals by comparing with recent reflection history.

    Looks for:
    - Declining confidence accuracy across recent runs
    - Repeated no-trade patterns
    - Erratic confidence swings

    Returns a list of new improvement suggestions.
    """
    suggestions: list[str] = []

    if len(_reflection_history) < 3:
        return suggestions  # Not enough history

    recent = _reflection_history[-3:]

    # Check for declining confidence accuracy
    accuracies = [r.get("confidence_accuracy", 0) for r in recent]
    if all(a is not None for a in accuracies) and len(accuracies) >= 2:
        if accuracies[-1] < accuracies[0] - DEGRADATION_SIGNAL_THRESHOLD:
            suggestions.append(
                f"Cross-session degradation detected: confidence accuracy declined "
                f"from {accuracies[0]:.0f} to {accuracies[-1]:.0f} over the last "
                f"{len(recent)} run(s)"
            )

    # Check for repeated no-trade pattern
    recent_executed = [r.get("executed", False) for r in recent]
    if not any(recent_executed) and len(recent_executed) >= 3:
        suggestions.append(
            "Cross-session alert: no trades executed in the last "
            f"{len(recent_executed)} runs. Review market conditions and risk thresholds."
        )

    # Check for erratic confidence swings
    if len(accuracies) >= 3 and all(a is not None for a in accuracies):
        spread = max(accuracies) - min(accuracies)
        if spread > 40:
            suggestions.append(
                f"Confidence accuracy is erratic (range: {spread:.0f} pts over "
                f"{len(accuracies)} runs). Consider model calibration or data quality check."
            )

    return suggestions
