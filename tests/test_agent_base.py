"""Tests for the base agent system."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from agents.base import AgentContext, BaseAgent, StubAgent


class _TestInput(BaseModel):
    value: str = Field(...)
    count: int = Field(default=0)


class _TestOutput(BaseModel):
    result: str = Field(...)
    length: int = Field(...)


class _TestAgent(BaseAgent[_TestInput, _TestOutput]):
    agent_name = "test_agent"
    input_schema = _TestInput
    output_schema = _TestOutput

    async def process(self, inputs: _TestInput) -> _TestOutput:
        return _TestOutput(
            result=f"processed: {inputs.value}",
            length=len(inputs.value),
        )


@pytest.fixture
def agent() -> _TestAgent:
    return _TestAgent()


@pytest.fixture
def context() -> AgentContext:
    return AgentContext(symbol="BTC/USD")


class TestAgentContext:
    def test_default_context(self) -> None:
        ctx = AgentContext()
        assert ctx.request_id, "request_id should be auto-generated"
        assert ctx.timestamp is not None, "timestamp should be auto-set"
        assert ctx.symbol == ""
        assert ctx.retry_count == 0

    def test_custom_context(self) -> None:
        ctx = AgentContext(symbol="ETH/USD", retry_count=2)
        assert ctx.symbol == "ETH/USD"
        assert ctx.retry_count == 2

    def test_context_with_session(self) -> None:
        ctx = AgentContext(session_id="test-session-123")
        assert ctx.session_id == "test-session-123"

    def test_context_auto_id_not_overwritten(self) -> None:
        ctx = AgentContext(request_id="custom-id")
        assert ctx.request_id == "custom-id"


class TestBaseAgent:
    async def test_agent_name_set(self, agent: _TestAgent) -> None:
        assert agent.agent_name == "test_agent"

    async def test_valid_run(self, agent: _TestAgent) -> None:
        output = await agent.run(_TestInput(value="hello"))
        assert output.result == "processed: hello"
        assert output.length == 5

    async def test_run_with_dict_input(self, agent: _TestAgent) -> None:
        output = await agent.run({"value": "world", "count": 3})
        assert output.result == "processed: world"
        assert output.length == 5
        assert output is not None

    async def test_run_logs_success(self, agent: _TestAgent) -> None:
        await agent.run(_TestInput(value="test"))
        assert agent.execution_log["success"] is True
        assert agent.execution_log["latency_ms"] is not None
        assert agent.execution_log["agent"] == "test_agent"

    async def test_run_logs_failure(self, agent: _TestAgent) -> None:
        agent.process = lambda x: (_ for _ in ()).throw(  # type: ignore[method-assign]
            ValueError("something broke")
        )

        with pytest.raises(ValueError, match="something broke"):
            await agent.run(_TestInput(value="test"))

        assert agent.execution_log["success"] is False
        assert "something broke" in agent.execution_log["error"]

    async def test_validate_input_valid(self, agent: _TestAgent) -> None:
        validated = agent.validate_input({"value": "ok", "count": 5})
        assert validated.value == "ok"
        assert validated.count == 5

    async def test_validate_input_invalid(self, agent: _TestAgent) -> None:
        with pytest.raises(Exception):
            agent.validate_input({"wrong_field": "value"})

    async def test_context_can_be_passed(self, context: AgentContext) -> None:
        agent_with_ctx = _TestAgent(context=context)
        output = await agent_with_ctx.run(_TestInput(value="context-test"))
        assert output.result == "processed: context-test"


class TestStubAgent:
    async def test_stub_raises_not_implemented(self) -> None:
        agent = StubAgent(target_agent="market_analyst")
        with pytest.raises(NotImplementedError) as exc_info:
            await agent.run({"value": "test"})
        assert "market_analyst" in str(exc_info.value)
        assert "not implemented" in str(exc_info.value)

    async def test_stub_agent_name(self) -> None:
        agent = StubAgent(target_agent="quant")
        assert agent.agent_name == "stub_quant"
