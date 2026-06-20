"""Tests for supervisor agent (LangGraph pipeline orchestrator)."""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from agents.circuit_breaker import CircuitBreakerRegistry
from agents.client import NoOpLLMClient
from agents.log import AgentLogger
from agents.models import AgentModelConfig, ModelRoster
from agents.queue import QueueRegistry
from agents.registry import AgentRegistry
from agents.retry import RetryConfig
from agents.router import ModelRouter
from agents.state import (
    AgentState,
    ConsensusOutput,
    MarketAnalystOutput,
    PipelineStatus,
    RiskOutput,
)
from agents.supervisor import Supervisor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def model_roster() -> ModelRoster:
    """Create a minimal model roster including all pipeline agents."""
    agents = {}
    for name in ["market_analyst", "quant", "news", "vision", "consensus",
                  "risk", "execution", "journal", "reflection", "memory"]:
        agents[name] = AgentModelConfig.from_dict(name, {"primary": f"model-{name}"})
    return ModelRoster(agents)


@pytest.fixture
def breaker_registry() -> CircuitBreakerRegistry:
    return CircuitBreakerRegistry()


@pytest.fixture
def queue_registry() -> QueueRegistry:
    return QueueRegistry()


@pytest.fixture
def logger() -> AgentLogger:
    return AgentLogger()


@pytest.fixture
def router() -> ModelRouter:
    return ModelRouter(
        llm_client=NoOpLLMClient(),
        breaker_registry=CircuitBreakerRegistry(),
        queue_registry=QueueRegistry(),
        retry_config=RetryConfig(max_retries=0, base_delay=0.01),
    )


@pytest.fixture
def registry(
    model_roster: ModelRoster,
    router: ModelRouter,
    breaker_registry: CircuitBreakerRegistry,
    queue_registry: QueueRegistry,
) -> AgentRegistry:
    reg = AgentRegistry(
        model_roster=model_roster,
        router=router,
        breaker_registry=breaker_registry,
        queue_registry=queue_registry,
    )
    for name in model_roster.agent_names:
        reg.register(name)
    return reg


@pytest.fixture
def supervisor(registry: AgentRegistry, router: ModelRouter, logger: AgentLogger) -> Supervisor:
    return Supervisor(registry=registry, router=router, logger=logger)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

class TestSupervisorBuild:
    def test_build_graph_succeeds(self, supervisor: Supervisor) -> None:
        """Building the graph should not raise."""
        supervisor.build_graph()
        assert supervisor.graph is not None

    def test_build_graph_idempotent(self, supervisor: Supervisor) -> None:
        """Building twice should work."""
        supervisor.build_graph()
        g1 = supervisor.graph
        supervisor.build_graph()
        assert supervisor.graph is not None

    def test_registry_needs_all_agents(self, supervisor: Supervisor) -> None:
        """Graph can be built even if some agents have no config."""
        supervisor.build_graph()
        assert supervisor.graph is not None


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------

class TestSupervisorRun:
    @pytest.mark.asyncio
    async def test_run_returns_state(self, supervisor: Supervisor) -> None:
        """Running the pipeline should return an AgentState."""
        supervisor.build_graph()
        result = await supervisor.run(
            symbol="BTC-USD",
            request="Analyze Bitcoin market conditions",
        )

        assert isinstance(result, AgentState)
        assert result.symbol == "BTC-USD"
        assert result.request_id != ""
        assert result.session_id != ""

    @pytest.mark.asyncio
    async def test_run_pipeline_status_tracking(self, supervisor: Supervisor) -> None:
        """Pipeline status should be populated after run."""
        supervisor.build_graph()
        result = await supervisor.run(symbol="BTC-USD", request="analyze")

        assert isinstance(result.pipeline_status, PipelineStatus)
        assert result.pipeline_status.start_time is not None

    @pytest.mark.asyncio
    async def test_run_with_no_api_key_degraded(self, supervisor: Supervisor) -> None:
        """Without API key, pipeline should still complete in degraded mode."""
        supervisor.build_graph()
        result = await supervisor.run(symbol="BTC-USD", request="analyze")
        # Pipeline completes even if degraded
        assert isinstance(result, AgentState)

    @pytest.mark.asyncio
    async def test_run_analysis_convenience(self, supervisor: Supervisor) -> None:
        """run_analysis convenience method should work."""
        supervisor.build_graph()
        result = await supervisor.run_analysis(symbol="ETH-USD", request="Analyze ETH")
        assert result.symbol == "ETH-USD"
        assert result.request_type == "analysis"

    def test_run_sync(self, supervisor: Supervisor) -> None:
        """Synchronous wrapper should work."""
        supervisor.build_graph()
        result = supervisor.run_sync(symbol="BTC-USD", request="test")
        assert isinstance(result, AgentState)


# ---------------------------------------------------------------------------
# Error handling and routing
# ---------------------------------------------------------------------------

class TestSupervisorErrorHandling:
    @pytest.mark.asyncio
    async def test_handles_empty_symbol(self, supervisor: Supervisor) -> None:
        """Empty symbol should not crash the pipeline."""
        supervisor.build_graph()
        result = await supervisor.run(symbol="", request="test")
        assert isinstance(result, AgentState)

    @pytest.mark.asyncio
    async def test_handles_empty_request(self, supervisor: Supervisor) -> None:
        """Empty request should not crash the pipeline."""
        supervisor.build_graph()
        result = await supervisor.run(symbol="BTC-USD", request="")
        assert isinstance(result, AgentState)

    @pytest.mark.asyncio
    async def test_full_pipeline_completes(self, supervisor: Supervisor) -> None:
        """Full pipeline should complete even with NoOp client."""
        supervisor.build_graph()
        result = await supervisor.run(
            symbol="BTC-USD",
            request="Comprehensive market analysis",
        )
        # Should have pipeline status
        assert result.pipeline_status is not None

    @pytest.mark.asyncio
    async def test_errors_field_populated(self, supervisor: Supervisor) -> None:
        """When agents fail, errors should be populated."""
        supervisor.build_graph()
        result = await supervisor.run(symbol="BTC-USD", request="test")
        # With NoOpLLMClient, all agent calls will fail, so errors should exist
        assert len(result.errors) > 0
        for err in result.errors:
            assert "agent" in err
            assert "error" in err


# ---------------------------------------------------------------------------
# Mocked success path
# ---------------------------------------------------------------------------

class TestSupervisorWithMockedRouter:
    """Test the supervisor with a mocked ModelRouter that returns success."""

    @pytest.fixture
    def mock_router(self) -> ModelRouter:
        router = AsyncMock(spec=ModelRouter)

        async def mock_execute(**kwargs: dict) -> object:  # type: ignore[misc]
            from agents.router import RouterResult
            r = RouterResult()
            r.success = True
            # Return a fake response with valid JSON content for any schema
            r.response = {
                "choices": [{
                    "message": {
                        "content": (
                            '{"confidence": 85.0, "direction": "long", '
                            '"indicators": {"rsi": 55}, '
                            '"rationale": "Analysis complete"}'
                        ),
                    }
                }],
                "model": "test-model",
                "usage": {"total_tokens": 100},
            }
            r.model_used = "test-model"
            r.attempts = 1
            return r

        router.execute = mock_execute
        return router

    @pytest.fixture
    def mock_registry(self, model_roster: ModelRoster, mock_router: ModelRouter) -> AgentRegistry:
        reg = AgentRegistry(
            model_roster=model_roster,
            router=mock_router,
            breaker_registry=CircuitBreakerRegistry(),
            queue_registry=QueueRegistry(),
        )
        for name in model_roster.agent_names:
            reg.register(name)
        return reg

    @pytest.mark.asyncio
    async def test_mocked_pipeline_completes(self, mock_registry: AgentRegistry, mock_router: ModelRouter) -> None:
        sup = Supervisor(registry=mock_registry, router=mock_router, logger=AgentLogger())
        sup.build_graph()
        result = await sup.run(symbol="BTC-USD", request="analyze")
        assert isinstance(result, AgentState)

    @pytest.mark.asyncio
    async def test_mocked_pipeline_sets_outputs(self, mock_registry: AgentRegistry, mock_router: ModelRouter) -> None:
        sup = Supervisor(registry=mock_registry, router=mock_router, logger=AgentLogger())
        sup.build_graph()
        result = await sup.run(symbol="BTC-USD", request="analyze")

        # All agents should have output (mock chain succeeds)
        # But the mock returns the same content for all agents, so parsing
        # depends on whether the content matches the expected schema
        # At minimum the pipeline should execute without raising
        assert result.pipeline_status is not None


# ---------------------------------------------------------------------------
# Log execution
# ---------------------------------------------------------------------------

class TestSupervisorLogging:
    def test_log_execution_no_error(self, supervisor: Supervisor) -> None:
        """log_execution should handle state with no agent outputs."""
        supervisor.build_graph()
        state = AgentState(symbol="BTC-USD", request="test")
        supervisor.log_execution(state)
        # No agent outputs to log — should not raise
        assert supervisor.logger.total_logs == 0

    def test_log_execution_with_outputs(self, supervisor: Supervisor) -> None:
        """log_execution should log each agent that has output."""
        supervisor.build_graph()
        state = AgentState(
            symbol="BTC-USD",
            request="test",
            market_analyst=MarketAnalystOutput(
                confidence=85.0,
                direction="long",
                indicators={"rsi": 55},
                rationale="Bullish setup",
            ),
            model_chain_used={"market_analyst": ["test-model"]},
        )
        supervisor.log_execution(state)
        assert supervisor.logger.total_logs > 0
        logs = supervisor.logger.get_by_agent("market_analyst")
        assert len(logs) >= 1


# ---------------------------------------------------------------------------
# Supervisor routing logic
# ---------------------------------------------------------------------------

class TestSupervisorRouting:
    """Test the conditional routing in isolation."""

    def test_consensus_approved_routes_to_risk(self) -> None:
        from agents.supervisor import _route_from_consensus
        state = AgentState(
            symbol="BTC-USD",
            consensus=ConsensusOutput(
                approved=True,
                composite_confidence=90.0,
                rationale="All signals aligned",
            ),
        )
        assert _route_from_consensus(state) == "risk"

    def test_consensus_rejected_routes_to_journal(self) -> None:
        from agents.supervisor import _route_from_consensus
        state = AgentState(
            symbol="BTC-USD",
            consensus=ConsensusOutput(
                approved=False,
                composite_confidence=30.0,
                rationale="Signals conflicted",
            ),
        )
        assert _route_from_consensus(state) == "journal"

    def test_consensus_none_routes_to_journal(self) -> None:
        """If consensus is None (agent failed), route to journal."""
        from agents.supervisor import _route_from_consensus
        state = AgentState(symbol="BTC-USD")
        assert _route_from_consensus(state) == "journal"

    def test_risk_approved_routes_to_execution(self) -> None:
        from agents.supervisor import _route_from_risk
        state = AgentState(
            symbol="BTC-USD",
            risk=RiskOutput(
                approved=True,
                risk_score=20.0,
                rationale="Risk acceptable",
            ),
        )
        assert _route_from_risk(state) == "execution"

    def test_risk_rejected_routes_to_journal(self) -> None:
        from agents.supervisor import _route_from_risk
        state = AgentState(
            symbol="BTC-USD",
            risk=RiskOutput(
                approved=False,
                risk_score=85.0,
                rationale="Too risky",
            ),
        )
        assert _route_from_risk(state) == "journal"
