"""Supervisor Agent — LangGraph-based pipeline orchestrator.

Routes incoming requests through the full agent pipeline:

    Supervisor → [Market Analyst, Quant, News, Vision] → Consensus
    → Risk → Execution → Journal → Reflection → Memory

Per RELIABILITY section:
- If a required agent fails, the pipeline degrades gracefully
- "No signal" = "no trade" — a hard failure in any required agent
  causes trade rejection, never silent approval
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.base import BaseAgent
from agents.circuit_breaker import CircuitBreakerRegistry
from agents.client import LLMClient, NoOpLLMClient
from agents.log import AgentLogger
from agents.models import AgentModelConfig
from agents.queue import QueueRegistry
from agents.registry import AgentRegistry
from agents.retry import RetryConfig
from agents.router import ModelRouter
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

# ---------------------------------------------------------------------------
# Agent output schema registry — maps agent names to their Pydantic models
# ---------------------------------------------------------------------------

AGENT_OUTPUT_SCHEMAS: dict[str, type[Any]] = {
    "market_analyst": MarketAnalystOutput,
    "quant": QuantOutput,
    "news": NewsOutput,
    "vision": VisionOutput,
    "consensus": ConsensusOutput,
    "risk": RiskOutput,
    "execution": ExecutionOutput,
    "journal": JournalOutput,
    "reflection": ReflectionOutput,
    "memory": MemoryOutput,
}

# Pipeline order (as defined in CLAUDE.md)
PIPELINE_ORDER = [
    "market_analyst",
    "quant",
    "news",
    "vision",
    "consensus",
    "risk",
    "execution",
    "journal",
    "reflection",
    "memory",
]

# Required agents — if these fail, the pipeline must reject the trade
REQUIRED_AGENTS = {"market_analyst", "quant", "consensus", "risk"}

# Agents that gate the pipeline continuation
APPROVAL_GATES = {"consensus", "risk"}


# ---------------------------------------------------------------------------
# Node builder helpers
# ---------------------------------------------------------------------------

def _build_agent_messages(
    agent_name: str,
    state: AgentState,
    model_config: AgentModelConfig,
) -> list[dict[str, str]]:
    """Build chat messages for an agent from the current state."""
    system_prompt = (
        f"You are the {agent_name.replace('_', ' ').title()} Agent in the ARES AI trading system.\n"
        f"Analyze the current state and produce a structured JSON response matching your schema.\n"
        f"Return ONLY valid JSON without markdown formatting or explanation."
    )

    context_parts = [
        f"Session: {state.session_id}",
        f"Symbol: {state.symbol}",
        f"Request: {state.request}",
    ]

    # Include previous agent outputs for context
    for prev_agent in PIPELINE_ORDER:
        output = getattr(state, prev_agent, None)
        if output is not None:
            context_parts.append(f"\n{prev_agent}_output:\n{output.model_dump_json(indent=2)}")

    user_content = "\n".join(context_parts)

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def _try_parse_output(
    response_text: str | None,
    schema: type[Any],
    agent_name: str,
) -> tuple[Any | None, str | None]:
    """Try to parse JSON text into the typed output schema.

    Returns (parsed_output, error_message).
    If parsing succeeds, error_message is None.
    If parsing fails, parsed_output is None and error_message describes the issue.
    """
    if not response_text:
        return None, f"Empty response from {agent_name} agent"

    # Strip markdown fences if present
    text = response_text.strip()
    if text.startswith("```"):
        # Remove ```json ... ``` or just ```
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON from {agent_name} agent: {e}"

    try:
        parsed = schema.model_validate(data)
        return parsed, None
    except Exception as e:
        return None, f"Schema validation failed for {agent_name}: {e}"


async def _execute_agent_node(
    agent_name: str,
    state: AgentState,
    router: ModelRouter,
    model_config: AgentModelConfig,
) -> dict[str, Any]:
    """Execute a single agent in the pipeline.

    Returns a state update dict with the agent's output (or error info).
    This is the core execution helper used by all LangGraph nodes.
    """
    update: dict[str, Any] = {}
    update["pipeline_status"] = PipelineStatus(
        current_node=agent_name,
        completed_nodes=state.pipeline_status.completed_nodes + [agent_name],
        failed_nodes=list(state.pipeline_status.failed_nodes),
        skipped_nodes=list(state.pipeline_status.skipped_nodes),
        start_time=state.pipeline_status.start_time,
    )
    update["pipeline_status"].current_node = agent_name
    update["pipeline_status"].completed_nodes = state.pipeline_status.completed_nodes.copy()
    update["pipeline_status"].failed_nodes = state.pipeline_status.failed_nodes.copy()
    update["pipeline_status"].skipped_nodes = state.pipeline_status.skipped_nodes.copy()
    update["pipeline_status"].start_time = state.pipeline_status.start_time

    # Get output schema
    schema = AGENT_OUTPUT_SCHEMAS.get(agent_name)
    if schema is None:
        update["pipeline_status"].failed_nodes = update["pipeline_status"].failed_nodes + [agent_name]
        update["errors"] = state.errors + [{
            "agent": agent_name,
            "error": f"No output schema registered for agent '{agent_name}'",
            "error_type": "schema_error",
        }]
        return update

    # Build messages for this agent
    messages = _build_agent_messages(agent_name, state, model_config)

    # Execute via model router
    router_result = await router.execute(
        model_chain=model_config.model_chain,
        messages=messages,
        temperature=model_config.temperature,
        max_tokens=model_config.max_tokens,
        rpm=model_config.rpm,
    )

    # Record model chain used
    update["model_chain_used"] = {
        **state.model_chain_used,
        agent_name: model_config.model_chain,
    }

    # Merge errors
    all_errors = list(state.errors)
    for err in router_result.errors:
        all_errors.append({
            "agent": agent_name,
            "model": err.get("model", ""),
            "error": err.get("error", ""),
            "error_type": err.get("error_type", ""),
        })

    if router_result.degraded:
        update["degraded"] = True

    # Parse response if successful
    if router_result.success and router_result.response:
        response_text = router_result.response.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed, parse_error = _try_parse_output(response_text, schema, agent_name)

        if parsed is not None:
            # Success — set the output
            update[agent_name] = parsed
            update["pipeline_status"].completed_nodes = state.pipeline_status.completed_nodes + [agent_name]
            update["errors"] = all_errors
            return update
        else:
            all_errors.append({
                "agent": agent_name,
                "model": router_result.model_used,
                "error": parse_error,
                "error_type": "parse_error",
            })

    # Agent failed — if required, mark as degraded
    if agent_name in REQUIRED_AGENTS:
        update["degraded"] = True

    update["pipeline_status"].failed_nodes = state.pipeline_status.failed_nodes + [agent_name]
    update["errors"] = all_errors
    return update


# ---------------------------------------------------------------------------
# LangGraph node functions
# ---------------------------------------------------------------------------

def _make_node_fn(agent_name: str):
    """Factory: creates a LangGraph node function for an agent."""
    async def node_fn(state: AgentState) -> dict[str, Any]:
        context = _get_agent_context(state)
        model_config = context["agent_configs"].get(agent_name)
        router = context["router"]
        registry = context.get("registry")

        if model_config is None:
            return {
                "pipeline_status": _merge_pipeline_status(state, failed=[agent_name]),
                "errors": state.errors + [{
                    "agent": agent_name,
                    "error": f"No model config for agent '{agent_name}'",
                    "error_type": "config_error",
                }],
            }

        # Check for registered agent implementation
        if registry and registry.has_agent(agent_name):
            reg = registry.get(agent_name)
            if reg.agent is not None and not reg.agent.__class__.__name__.startswith("Stub"):
                agent_class = type(reg.agent) if not isinstance(reg.agent, type) else reg.agent
                return await _execute_agent_impl(
                    agent_name, state, agent_class, model_config, router,
                )

        return await _execute_agent_node(agent_name, state, router, model_config)
    return node_fn


def _merge_pipeline_status(
    state: AgentState,
    completed: list[str] | None = None,
    failed: list[str] | None = None,
    skipped: list[str] | None = None,
) -> PipelineStatus:
    """Merge new status entries into existing pipeline status."""
    return PipelineStatus(
        current_node="",
        completed_nodes=state.pipeline_status.completed_nodes + (completed or []),
        failed_nodes=state.pipeline_status.failed_nodes + (failed or []),
        skipped_nodes=state.pipeline_status.skipped_nodes + (skipped or []),
        start_time=state.pipeline_status.start_time,
    )


# ---------------------------------------------------------------------------
# Router functions
# ---------------------------------------------------------------------------

def _route_from_supervisor(state: AgentState) -> str:
    """Route from supervisor to the first pipeline agent."""
    return "market_analyst"


def _route_from_consensus(state: AgentState) -> str:
    """After consensus, route based on approval."""
    if state.consensus and state.consensus.approved:
        return "risk"
    # Rejected — skip risk and execution, go to journal
    return "journal"


def _route_from_risk(state: AgentState) -> str:
    """After risk, route based on approval."""
    if state.risk and state.risk.approved:
        return "execution"
    # Rejected — skip execution, go to journal
    return "journal"


def _route_after_agent(state: AgentState, current: str) -> str:
    """Determine the next agent after `current` in the pipeline."""
    pipeline = PIPELINE_ORDER
    try:
        idx = pipeline.index(current)
    except ValueError:
        return END

    # Find the next non-skipped agent
    for next_agent in pipeline[idx + 1:]:
        # Skip vision if it has no fallback and we detect it's unavailable
        # (Handled by the node itself — just route normally)
        return next_agent

    return END


async def _consensus_node_fn(state: AgentState) -> dict[str, Any]:
    """Deterministic consensus evaluation node.

    Replaces the generic LLM node for consensus. Evaluates Market Analyst
    and Quant outputs against confidence thresholds without an LLM call.
    """
    from agents.consensus import ConsensusEngine

    ma = state.market_analyst.model_dump() if state.market_analyst else None
    q = state.quant.model_dump() if state.quant else None
    result = ConsensusEngine.evaluate(state.symbol, ma, q)

    return {"consensus": ConsensusOutput(**result)}


async def _vision_node_fn(state: AgentState) -> dict[str, Any]:
    """Deterministic vision analysis node.

    Runs rule-based chart pattern detection on available data.
    Advisory/non-blocking — never causes pipeline failure.
    Always produces a VisionOutput even when data is sparse.
    """
    from agents.vision import VisionAgent, VisionInput

    # Build synthetic candles from market_analyst indicators if available
    candles: list[dict[str, Any]] = []
    if state.market_analyst and state.market_analyst.indicators:
        indicators = state.market_analyst.indicators
        # Create synthetic data points from indicator values
        # for pattern detection
        for name, value in indicators.items():
            candles.append({
                "open": float(value),
                "high": float(value) * 1.01,
                "low": float(value) * 0.99,
                "close": float(value),
                "volume": 0,
            })

    agent = VisionAgent()

    # Check available models from config for fallback tracking
    ctx = _get_agent_context(state)
    vision_config = ctx.get("agent_configs", {}).get("vision")
    model_chain = vision_config.model_chain if vision_config else []
    primary_model = model_chain[0] if model_chain else None
    fallback_model = model_chain[1] if len(model_chain) > 1 else None
    model_available = bool(primary_model)

    if model_available:
        agent.model_available = True

    try:
        raw_result = await agent.run(VisionInput(
            symbol=state.symbol,
            candles=candles,
        ))
        
        # Convert Pydantic FlexibleSchema to dict
        result = raw_result.model_dump() if hasattr(raw_result, "model_dump") else raw_result
        
        result["fallback_model"] = fallback_model
        result["available"] = model_available
        return {"vision": VisionOutput(**result)}
    except Exception as e:
        # Vision never blocks — return degraded result on any error
        return {
            "vision": VisionOutput(
                chart_pattern=None,
                confidence=0.0,
                support_levels=[],
                resistance_levels=[],
                available=False,
                fallback_model=fallback_model,
                rationale=f"Vision analysis unavailable: {e}",
            ),
        }

class _GraphContext:
    """Holding context injected into the graph at build time."""

    def __init__(
        self,
        router: ModelRouter,
        agent_configs: dict[str, AgentModelConfig],
        registry: AgentRegistry | None = None,
    ) -> None:
        self.router = router
        self.agent_configs = agent_configs
        self.registry = registry


_context: _GraphContext | None = None


def _get_agent_context(state: AgentState) -> dict[str, Any]:
    """Get the injected graph context."""
    if _context is None:
        raise RuntimeError("Supervisor graph not initialized. Call Supervisor.build_graph() first.")
    return {
        "router": _context.router,
        "agent_configs": _context.agent_configs,
        "registry": _context.registry,
    }


async def _execute_agent_impl(
    agent_name: str,
    state: AgentState,
    agent_class: type[BaseAgent[Any, Any]],
    model_config: AgentModelConfig,
    router: ModelRouter,
) -> dict[str, Any]:
    """Execute a registered agent implementation directly.

    Instantiates the agent, builds input from state, and calls agent.run().
    This is the async path used by LangGraph nodes (M4+ real agents).
    """
    from agents.base import AgentContext as AgentCtx

    update: dict[str, Any] = {}
    update["pipeline_status"] = _merge_pipeline_status(state, completed=[agent_name])
    update["pipeline_status"].current_node = agent_name

    # Build AgentContext for this call
    agent_ctx = AgentCtx(
        session_id=state.session_id,
        request_id=state.request_id,
        symbol=state.symbol,
        model_preferences={
            "model_chain": model_config.model_chain,
            "rpm": model_config.rpm,
            "temperature": model_config.temperature,
            "max_tokens": model_config.max_tokens,
        },
    )

    # Build input from state — include previous agent outputs for downstream agents
    input_data: dict[str, Any] = {
        "symbol": state.symbol,
        "interval": "1d",
        "lookback": 100,
        "request": state.request,
    }
    for prev in PIPELINE_ORDER:
        if prev == agent_name:
            break
        output = getattr(state, prev, None)
        if output is not None:
            input_data[f"{prev}_output"] = output.model_dump()

    try:
        agent_instance = agent_class(router=router, context=agent_ctx)
        output = await agent_instance.run(input_data)

        # Set the output
        update[agent_name] = output
        update["model_chain_used"] = {
            **state.model_chain_used,
            agent_name: model_config.model_chain,
        }
        return update

    except Exception as e:
        update["pipeline_status"].failed_nodes = state.pipeline_status.failed_nodes + [agent_name]
        update["errors"] = state.errors + [{
            "agent": agent_name,
            "error": str(e),
            "error_type": type(e).__name__,
        }]
        if agent_name in REQUIRED_AGENTS:
            update["degraded"] = True
        return update


# ---------------------------------------------------------------------------
# Node factory: creates all nodes with routing based on pipeline order
# ---------------------------------------------------------------------------

def _build_pipeline_nodes(graph: StateGraph) -> None:
    """Add all pipeline nodes and edges to the graph."""
    # Add supervisor node
    async def supervisor_node(state: AgentState) -> dict[str, Any]:
        return _supervisor_entry(state)

    graph.add_node("supervisor", supervisor_node)
    graph.add_edge(START, "supervisor")

    # Add agent nodes
    for agent_name in PIPELINE_ORDER:
        if agent_name == "consensus":
            # Consensus is deterministic — use a custom node, not the LLM path
            graph.add_node("consensus", _consensus_node_fn)
        elif agent_name == "vision":
            # Vision is advisory/deterministic — never blocks pipeline
            graph.add_node("vision", _vision_node_fn)
        else:
            graph.add_node(agent_name, _make_node_fn(agent_name))

    # Add edges with routing
    graph.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {agent: agent for agent in PIPELINE_ORDER},
    )

    # Standard edges between consecutive agents
    graph.add_edge("market_analyst", "quant")
    graph.add_edge("quant", "news")
    graph.add_edge("news", "vision")
    graph.add_edge("vision", "consensus")

    # Consensus → risk or journal
    graph.add_conditional_edges(
        "consensus",
        _route_from_consensus,
        {"risk": "risk", "journal": "journal"},
    )

    # Risk → execution or journal
    graph.add_conditional_edges(
        "risk",
        _route_from_risk,
        {"execution": "execution", "journal": "journal"},
    )

    # Remaining chain
    graph.add_edge("execution", "journal")
    graph.add_edge("journal", "reflection")
    graph.add_edge("reflection", "memory")
    graph.add_edge("memory", END)


def _supervisor_entry(state: AgentState) -> dict[str, Any]:
    """Entry point — initialize the pipeline state."""
    now = datetime.now(UTC).isoformat()
    return {
        "pipeline_status": PipelineStatus(
            current_node="supervisor",
            completed_nodes=["supervisor"],
            failed_nodes=[],
            skipped_nodes=[],
            start_time=now,
        ),
        "request_id": state.request_id or str(uuid.uuid4()),
        "session_id": state.session_id or str(uuid.uuid4()),
    }


# ---------------------------------------------------------------------------
# Supervisor class (public API)
# ---------------------------------------------------------------------------

class Supervisor:
    """LangGraph-based pipeline orchestrator.

    Builds and runs the full agent pipeline as a LangGraph StateGraph.
    Each pipeline step is an agent node with typed I/O, circuit breaker,
    rate limiting, and fallback chains.

    Usage:
        supervisor = Supervisor(registry, router, logger)
        supervisor.build_graph()
        result = await supervisor.run(AgentState(symbol="BTC-USD", request="Analyze BTC"))
    """

    def __init__(
        self,
        registry: AgentRegistry,
        router: ModelRouter,
        logger: AgentLogger,
    ) -> None:
        self.registry = registry
        self.router = router
        self.logger = logger
        self.graph = None
        self._agent_configs: dict[str, AgentModelConfig] = {}

    def build_graph(self) -> None:
        """Build the LangGraph state graph.

        Must be called before run().
        """
        global _context

        # Collect model configs from registry
        self._agent_configs = {}
        for name in PIPELINE_ORDER:
            try:
                reg = self.registry.get(name)
                if reg.model_config:
                    self._agent_configs[name] = reg.model_config
            except KeyError:
                continue

        # Inject context
        _context = _GraphContext(
            router=self.router,
            agent_configs=self._agent_configs,
            registry=self.registry,
        )

        # Build graph
        builder = StateGraph(AgentState)
        _build_pipeline_nodes(builder)
        self.graph = builder.compile()

    async def run(self, initial_state: AgentState | None = None, **kwargs: Any) -> AgentState:
        """Run the full agent pipeline.

        Args:
            initial_state: Pre-built AgentState, or...
            **kwargs: Fields to pass to AgentState constructor.

        Returns:
            Final AgentState with all agent outputs populated.
        """
        if self.graph is None:
            self.build_graph()

        state = initial_state or AgentState(**kwargs)
        if not state.request_id:
            state.request_id = str(uuid.uuid4())
        if not state.session_id:
            state.session_id = str(uuid.uuid4())

        result = await self.graph.ainvoke(state)
        return AgentState.model_validate(result)

    async def run_analysis(self, symbol: str, request: str) -> AgentState:
        """Convenience: run a full analysis pipeline for a symbol."""
        return await self.run(
            symbol=symbol,
            request=request,
            request_type="analysis",
        )

    def run_sync(self, **kwargs: Any) -> AgentState:
        """Synchronous convenience wrapper for testing."""
        import asyncio
        return asyncio.run(self.run(**kwargs))

    def get_graph(self) -> Any | None:
        """Get the compiled graph (for visualization)."""
        return self.graph

    def log_execution(self, state: AgentState) -> None:
        """Log all agent outputs from a completed run."""
        now = datetime.now(UTC).isoformat()

        for agent_name in PIPELINE_ORDER:
            output = getattr(state, agent_name, None)
            if output is not None:
                chain = state.model_chain_used.get(agent_name, [])
                self.logger.log(
                    agent_name=agent_name,
                    model_id=chain[0] if chain else "unknown",
                    latency_ms=state.total_latency_ms,
                    fallback_used=len(chain) > 1,
                    degraded=state.degraded,
                    output_schema=output.model_dump() if hasattr(output, "model_dump") else None,
                )
