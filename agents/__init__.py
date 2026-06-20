"""Agents package — multi-agent trading system.

Implements the RELIABILITY and AGENT I/O CONTRACTS sections of CLAUDE.md.
"""

from agents.base import AgentContext, BaseAgent, FlexibleSchema, StubAgent
from agents.circuit_breaker import (
    CircuitBreakerRegistry,
    CircuitState,
    ModelCircuitBreaker,
    NoOpBreaker,
)
from agents.client import LLMClient, NoOpLLMClient, create_llm_client
from agents.consensus import ConsensusEngine
from agents.improvement import (
    IMPROVEMENT_MAX_HISTORY,
    MIN_RUNS_FOR_ANALYSIS,
    ImprovementRecord,
    ImprovementRunResult,
    StrategyImprovementEngine,
    get_improvement_engine,
    reset_engine,
)
from agents.log import AgentLogger
from agents.market_analyst import MarketAnalystAgent, MarketAnalystInput
from agents.models import AgentModelConfig, ModelRoster, load_model_roster
from agents.quant import QuantAgent, QuantInput
from agents.queue import ModelRequestQueue, QueueRegistry
from agents.registry import AgentRegistration, AgentRegistry
from agents.retry import RetryConfig, RetryResult, with_retry
from agents.execution import ExecutionAgent, ExecutionInput
from agents.journal import JournalAgent, JournalInput
from agents.memory import MemoryAgent, MemoryInput
from agents.reflection import ReflectionAgent, ReflectionInput
from agents.risk import RiskAgent, RiskInput
from agents.router import ModelRouter, RouterResult
from agents.state import (
    AgentState,
    ConsensusOutput,
    ExecutionOutput,
    JournalOutput,
    MarketAnalystOutput,
    MemoryOutput,
    NewsOutput,
    PipelineStatus,
    QuantOutput,
    ReflectionOutput,
    RiskOutput,
    VisionOutput,
)
from agents.supervisor import Supervisor
from agents.vision import VisionAgent, VisionInput

__all__ = [
    "AgentContext",
    "BaseAgent",
    "FlexibleSchema",
    "StubAgent",
    "ExecutionAgent",
    "ExecutionInput",
    "JournalAgent",
    "JournalInput",
    "MemoryAgent",
    "MemoryInput",
    "ReflectionAgent",
    "ReflectionInput",
    "StrategyImprovementEngine",
    "ImprovementRecord",
    "ImprovementRunResult",
    "get_improvement_engine",
    "reset_engine",
    "ModelCircuitBreaker",
    "CircuitBreakerRegistry",
    "CircuitState",
    "NoOpBreaker",
    "LLMClient",
    "NoOpLLMClient",
    "create_llm_client",
    "AgentLogger",
    "ConsensusEngine",
    "MarketAnalystAgent",
    "MarketAnalystInput",
    "QuantAgent",
    "QuantInput",
    "AgentModelConfig",
    "ModelRoster",
    "load_model_roster",
    "ModelRequestQueue",
    "QueueRegistry",
    "RetryConfig",
    "RetryResult",
    "with_retry",
    "AgentRegistration",
    "AgentRegistry",
    "RiskAgent",
    "RiskInput",
    "ModelRouter",
    "RouterResult",
    "VisionAgent",
    "VisionInput",
    "AgentState",
    "MarketAnalystOutput",
    "QuantOutput",
    "NewsOutput",
    "RiskOutput",
    "ConsensusOutput",
    "ExecutionOutput",
    "JournalOutput",
    "ReflectionOutput",
    "MemoryOutput",
    "VisionOutput",
    "PipelineStatus",
    "Supervisor",
]
