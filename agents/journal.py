"""Journal Agent — post-trade recording and lesson extraction.

Records the pipeline run results in a structured journal entry,
extracting mistakes, lessons, and a human-readable summary.
Fully deterministic — no LLM calls.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agents.state import JournalOutput
from agents.base import AgentContext, BaseAgent


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class JournalInput(BaseModel):
    """Input for the Journal Agent.

    Receives all pipeline outputs via extra fields (``extra="allow"``)
    since the input shape depends on which agents have run.
    """

    symbol: str = Field(default="", description="Ticker symbol")
    request: str = Field(default="", description="Original user request")
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Journal Agent
# ---------------------------------------------------------------------------


class JournalAgent(BaseAgent[JournalInput, JournalOutput]):
    """Post-trade journaling and lesson extraction agent.

    Fully deterministic — no LLM calls. Examines pipeline outputs
    to produce a structured journal entry with mistakes, lessons,
    and a human-readable rationale.

    Usage::

        agent = JournalAgent()
        result = await agent.run(JournalInput(symbol="BTC-USD", ...))
    """

    agent_name: str = "journal"
    input_schema: type[BaseModel] = JournalInput
    output_schema: type[BaseModel] = JournalOutput

    def __init__(self, context: AgentContext | None = None, **kwargs) -> None:
        super().__init__(context=context)

    async def process(self, inputs: JournalInput) -> dict[str, Any]:
        """Generate a structured journal entry from pipeline outputs.

        1. Extract pipeline outputs from extra fields
        2. Detect mistakes (errors, rejections, low-confidence decisions)
        3. Extract lessons from the pipeline run
        4. Build a human-readable rationale
        """
        output_map = _extract_agent_outputs(inputs)
        symbol = inputs.symbol or "unknown"
        request = inputs.request or "No request"

        execution = output_map.get("execution", {})
        market_analyst = output_map.get("market_analyst", {})
        risk = output_map.get("risk", {})

        executed = bool(execution.get("executed", False))
        errors = output_map.get("errors", [])

        # --- Detect mistakes ---
        mistakes = _detect_mistakes(errors, market_analyst, risk, executed)

        # --- Extract lessons ---
        lessons = _extract_lessons(mistakes, executed)

        # --- Build rationale ---
        rationale_parts = [
            f"Journal entry for {symbol}",
            f"Request: {request}",
        ]

        if executed:
            direction = market_analyst.get("direction", "unknown")
            fill_price = execution.get("fill_price")
            rationale_parts.append(f"Trade executed: {direction} at ${fill_price:.2f}")
        else:
            reason = execution.get("rationale", "No trade executed")
            rationale_parts.append(f"Trade not executed: {reason}")

        if mistakes:
            rationale_parts.append(f"Detected {len(mistakes)} issue(s)")
        if lessons:
            rationale_parts.append(f"Extracted {len(lessons)} lesson(s)")

        rationale = " | ".join(rationale_parts)

        return {
            "entry_id": str(uuid.uuid4()),
            "mistakes": mistakes,
            "lessons": lessons,
            "rationale": rationale,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_agent_outputs(inputs: JournalInput) -> dict[str, Any]:
    """Extract agent outputs from the input's extra fields."""
    output_map: dict[str, Any] = {}
    agent_names = [
        "market_analyst", "quant", "news", "vision", "consensus",
        "risk", "execution",
    ]
    for name in agent_names:
        val = getattr(inputs, f"{name}_output", None)
        if val is not None:
            output_map[name] = val
    errors = getattr(inputs, "errors", None) or []
    if errors:
        output_map["errors"] = errors
    return output_map


def _detect_mistakes(
    errors: list[Any],
    market_analyst: dict[str, Any],
    risk: dict[str, Any],
    executed: bool,
) -> list[str]:
    """Detect potential mistakes or issues in the pipeline run."""
    mistakes: list[str] = []

    if errors:
        for err in errors:
            agent = err.get("agent", "unknown") if isinstance(err, dict) else "unknown"
            msg = err.get("error", str(err)) if isinstance(err, dict) else str(err)
            mistakes.append(f"Pipeline error in {agent}: {msg}")

    if not executed and market_analyst:
        direction = market_analyst.get("direction", "flat")
        if direction in ("long", "short"):
            mistakes.append(
                f"Signal generated ({direction}) but trade was not executed — "
                "review risk or consensus thresholds"
            )

    if risk:
        reasons = risk.get("reasons", [])
        if reasons:
            for reason in reasons:
                if "risk" in reason.lower():
                    mistakes.append(f"Risk concern: {reason}")

    return mistakes


def _extract_lessons(
    mistakes: list[str],
    executed: bool,
) -> list[str]:
    """Extract actionable lessons from the pipeline run."""
    lessons: list[str] = []

    if mistakes:
        lessons.append("Review pipeline errors and adjust agent thresholds as needed")
    else:
        lessons.append("Pipeline completed without errors — continue monitoring")

    if executed:
        lessons.append("Trade signal passed all gates — strategy alignment confirmed")
    else:
        lessons.append("Signal was filtered — verify risk and consensus parameters")

    return lessons
