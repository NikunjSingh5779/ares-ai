"""Memory Agent — session consolidation and memory retrieval.

Consolidates the current pipeline run into structured memory records
for future retrieval. In-memory only for M9 — ChromaDB vector storage
integration is deferred to a later milestone.

Fully deterministic — no LLM calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agents.state import MemoryOutput
from agents.base import AgentContext, BaseAgent


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class MemoryInput(BaseModel):
    """Input for the Memory Agent.

    Receives all pipeline outputs via extra fields (``extra="allow"``)
    since the input shape depends on which agents have run.
    """

    symbol: str = Field(default="", description="Ticker symbol")
    request: str = Field(default="", description="Original user request")
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Memory types
# ---------------------------------------------------------------------------

MEMORY_TYPE_MAP: dict[str, str] = {
    "execution": "trade",
    "market_analyst": "agent_output",
    "quant": "agent_output",
    "consensus": "agent_output",
    "risk": "agent_output",
}


# ---------------------------------------------------------------------------
# Memory Agent
# ---------------------------------------------------------------------------


class MemoryAgent(BaseAgent[MemoryInput, MemoryOutput]):
    """Post-trade memory consolidation agent.

    Extracts key information from each pipeline output and builds
    structured memory records. In-memory for M9 — no ChromaDB writes.

    Usage::

        agent = MemoryAgent()
        result = await agent.run(MemoryInput(symbol="BTC-USD", ...))
    """

    agent_name: str = "memory"
    input_schema: type[BaseModel] = MemoryInput
    output_schema: type[BaseModel] = MemoryOutput

    def __init__(self, context: AgentContext | None = None, **kwargs) -> None:
        super().__init__(context=context)

    async def process(self, inputs: MemoryInput) -> dict[str, Any]:
        """Consolidate the pipeline run into memory records.

        1. Extract outputs from all pipeline agents
        2. Build structured memory records from key outputs
        3. Mark consolidation as complete
        """
        output_map = _extract_agent_outputs(inputs)
        symbol = inputs.symbol or "unknown"
        request = inputs.request or "No request"

        execution = output_map.get("execution", {})
        market_analyst = output_map.get("market_analyst", {})

        # --- Build relevant memories ---
        memories: list[dict[str, Any]] = []

        # Memory from execution
        if execution:
            executed = bool(execution.get("executed", False))
            memories.append({
                "type": "trade",
                "content": (
                    f"{'Executed' if executed else 'Rejected'} "
                    f"trade for {symbol}. "
                    f"Fill price: ${execution.get('fill_price', 'N/A')}. "
                    f"Rationale: {execution.get('rationale', '')}"
                ),
                "importance": 7.0 if executed else 3.0,
                "timestamp": datetime.now(UTC).isoformat(),
            })

        # Memory from market analyst
        if market_analyst:
            direction = market_analyst.get("direction", "flat")
            confidence = market_analyst.get("confidence", 0)
            memories.append({
                "type": "agent_output",
                "content": (
                    f"Market analysis for {symbol}: {direction} "
                    f"at {confidence}% confidence. "
                    f"Rationale: {market_analyst.get('rationale', '')}"
                ),
                "importance": 5.0,
                "timestamp": datetime.now(UTC).isoformat(),
            })

        # Memory from risk if rejected
        risk = output_map.get("risk", {})
        if risk:
            approved = bool(risk.get("approved", True))
            if not approved:
                memories.append({
                    "type": "agent_output",
                    "content": (
                        f"Risk rejected trade for {symbol}. "
                        f"Score: {risk.get('risk_score', 'N/A')}. "
                        f"Reasons: {risk.get('reasons', [])}"
                    ),
                    "importance": 6.0,
                    "timestamp": datetime.now(UTC).isoformat(),
                })

        # Memory about the request context
        memories.append({
            "type": "user_preference",
            "content": f"User request: {request} for symbol {symbol}",
            "importance": 2.0,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        # --- Build rationale ---
        rationale_parts = [
            f"Memory consolidation for {symbol}:",
            f"{len(memories)} memory record(s) created",
        ]
        if execution:
            rationale_parts.append(
                "Executed" if execution.get("executed") else "Not executed",
            )

        return {
            "relevant_memories": memories,
            "consolidated": True,
            "rationale": " | ".join(rationale_parts),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_agent_outputs(inputs: MemoryInput) -> dict[str, Any]:
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
    return output_map
