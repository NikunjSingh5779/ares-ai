"""LangGraph state definitions for the agent pipeline.

Shared state schema for the multi-agent pipeline. Each agent receives
a typed slice of this state and returns its typed output.

Per AGENT I/O CONTRACTS: All agent inputs and outputs are Pydantic
models validated on receipt.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class MarketAnalystOutput(BaseModel):
    """Output from the Market Analyst Agent."""

    confidence: float = Field(..., ge=0, le=100, description="Confidence score (0-100)")
    direction: str = Field(..., pattern="^(long|short|flat)$")
    indicators: dict[str, float] = Field(
        default_factory=dict,
        description="Technical indicator values (e.g., {'rsi': 45.2, 'macd': 0.15})",
    )
    rationale: str = Field(..., description="Explanation of the analysis")


class QuantOutput(BaseModel):
    """Output from the Quant Agent."""

    confidence: float = Field(..., ge=0, le=100)
    direction: str = Field(..., pattern="^(long|short|flat)$")
    expected_return: Optional[float] = None
    strategy_name: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(...)


class NewsOutput(BaseModel):
    """Output from the News Agent."""

    sentiment: Optional[float] = None
    key_events: list[str] = Field(default_factory=list)
    impact_scores: dict[str, float] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    rationale: str = Field(...)


class RiskOutput(BaseModel):
    """Output from the Risk Agent."""

    approved: bool = False
    max_position_size: Optional[float] = None
    stop_loss: Optional[float] = None
    risk_score: float = Field(..., ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    rationale: str = Field(...)


class ConsensusOutput(BaseModel):
    """Output from the Consensus Engine."""

    approved: bool = False
    composite_confidence: float = Field(..., ge=0, le=100)
    agreement_metrics: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(...)


class ExecutionOutput(BaseModel):
    """Output from the Execution Agent."""

    executed: bool = False
    order_id: Optional[str] = None
    fill_price: Optional[float] = None
    filled_quantity: Optional[float] = None
    rationale: str = Field(...)


class JournalOutput(BaseModel):
    """Output from the Journal Agent."""

    entry_id: Optional[str] = None
    mistakes: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    rationale: str = Field(...)


class ReflectionOutput(BaseModel):
    """Output from the Reflection Agent."""

    evaluation: str = Field(...)
    confidence_accuracy: float = Field(..., ge=0, le=100)
    improvement_suggestions: list[str] = Field(default_factory=list)
    knowledge_updates: list[str] = Field(default_factory=list)


class MemoryOutput(BaseModel):
    """Output from the Memory Agent."""

    relevant_memories: list[dict[str, Any]] = Field(default_factory=list)
    consolidated: bool = False
    rationale: str = Field(...)


class VisionOutput(BaseModel):
    """Output from the Vision Agent (advisory, non-blocking)."""

    chart_pattern: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0, le=100)
    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)
    available: bool = True  # False when model is unreachable
    fallback_model: Optional[str] = None  # Fallback model used when primary unavailable
    rationale: str = Field(...)


class PipelineStatus(BaseModel):
    """Tracks which agents have been executed and their results."""

    current_node: str = ""
    completed_nodes: list[str] = Field(default_factory=list)
    failed_nodes: list[str] = Field(default_factory=list)
    skipped_nodes: list[str] = Field(default_factory=list)
    start_time: Optional[str] = None
    end_time: Optional[str] = None

    @property
    def all_completed(self) -> bool:
        return len(self.failed_nodes) == 0 and len(self.completed_nodes) > 0


class AgentState(BaseModel):
    """Shared state for the LangGraph agent pipeline.

    Tracks all agent outputs, pipeline progress, and error information.
    Updated as the pipeline executes node by node.
    """

    # Input
    request_id: str = ""
    session_id: str = ""
    symbol: str = ""
    request: str = ""
    request_type: str = "analysis"
    candles: Optional[list[Any]] = None

    # Agent outputs (populated as pipeline executes)
    market_analyst: Optional[MarketAnalystOutput] = None
    quant: Optional[QuantOutput] = None
    news: Optional[NewsOutput] = None
    vision: Optional[VisionOutput] = None
    consensus: Optional[ConsensusOutput] = None
    risk: Optional[RiskOutput] = None
    execution: Optional[ExecutionOutput] = None
    journal: Optional[JournalOutput] = None
    reflection: Optional[ReflectionOutput] = None
    memory: Optional[MemoryOutput] = None

    # Pipeline metadata
    pipeline_status: PipelineStatus = Field(default_factory=PipelineStatus)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    model_chain_used: dict[str, list[str]] = Field(default_factory=dict)
    degraded: bool = False
    total_latency_ms: int = 0
