"""Integration tests — patch the 4 metrics hooks and assert they fire during real flows.

These tests verify that:
1. ``record_agent_run`` fires during BaseAgent.run() on both success and error
2. ``record_agent_fallback`` fires when a ModelRouter uses a fallback model
3. ``set_kill_switch_active`` fires during KillSwitch.activate/auto_trigger/arm
4. ``record_live_order`` fires during LiveTradingEngine.execute_signal()
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from agents.base import AgentContext, BaseAgent
from agents.router import RouterResult
from live_trading import (
    ExchangeConnector,
    KillSwitch,
    LiveTradingEngine,
    ModeManager,
    PromotionGate,
    TradingMode,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SimpleInput(BaseModel):
    value: str = "test"


class _SimpleOutput(BaseModel):
    result: str = "ok"


class _SuccessAgent(BaseAgent[_SimpleInput, _SimpleOutput]):
    """Always succeeds."""

    agent_name: str = "test_success"
    input_schema: type[BaseModel] = _SimpleInput
    output_schema: type[BaseModel] = _SimpleOutput

    async def process(self, inputs: _SimpleInput) -> _SimpleOutput:
        return _SimpleOutput(result=f"processed_{inputs.value}")


class _FailingAgent(BaseAgent[_SimpleInput, _SimpleOutput]):
    """Always raises."""

    agent_name: str = "test_fail"
    input_schema: type[BaseModel] = _SimpleInput
    output_schema: type[BaseModel] = _SimpleOutput

    async def process(self, inputs: _SimpleInput) -> _SimpleOutput:
        msg = "deliberate failure"
        raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Tests: record_agent_run
# ---------------------------------------------------------------------------


class TestRecordAgentRunIntegration:
    """record_agent_run fires during real agent execution."""

    async def test_success_path(self) -> None:
        """Assert record_agent_run("test_success", "success") is called after a successful run."""
        agent = _SuccessAgent()

        with patch("agents.base.record_agent_run") as mock:
            await agent.run(_SimpleInput(value="hello"))

        mock.assert_called_once_with("test_success", "success")

    async def test_error_path(self) -> None:
        """Assert record_agent_run("test_fail", "error") is called before the exception propagates."""
        agent = _FailingAgent()

        with patch("agents.base.record_agent_run") as mock:
            with pytest.raises(RuntimeError, match="deliberate failure"):
                await agent.run(_SimpleInput(value="fail"))

        mock.assert_called_once_with("test_fail", "error")

    async def test_success_from_dict_input(self) -> None:
        """Assert the metric fires when input is a plain dict (coerced by run())."""
        agent = _SuccessAgent()

        with patch("agents.base.record_agent_run") as mock:
            await agent.run({"value": "from_dict"})

        mock.assert_called_once_with("test_success", "success")


# ---------------------------------------------------------------------------
# Tests: record_agent_fallback
# ---------------------------------------------------------------------------


class _FallbackAwareAgent(BaseAgent[_SimpleInput, _SimpleOutput]):
    """Agent that owns a mock router and checks fallback metrics."""

    agent_name: str = "fallback_test"
    input_schema: type[BaseModel] = _SimpleInput
    output_schema: type[BaseModel] = _SimpleOutput

    def __init__(self, router_result: RouterResult, context: AgentContext | None = None) -> None:
        super().__init__(context=context)
        self._result = router_result
        self.router = AsyncMock()
        self.router.execute = AsyncMock(return_value=router_result)

    async def process(self, inputs: _SimpleInput) -> _SimpleOutput:
        model_chain = ["primary-model", "fallback-model"]
        self.context.model_preferences["model_chain"] = model_chain
        router_result: RouterResult = await self.router.execute(
            model_chain=model_chain,
            messages=[{"role": "user", "content": "test"}],
        )
        if router_result.fallback_used:
            from backend.core.metrics import record_agent_fallback

            record_agent_fallback(
                self.agent_name,
                model_chain[0],
                router_result.model_used,
            )
        return _SimpleOutput(result="ok")


class TestRecordAgentFallbackIntegration:
    """record_agent_fallback fires when the router uses a fallback model."""

    async def test_fallback_recorded(self) -> None:
        """Assert the fallback metric fires with correct args when fallback_used is True."""
        result = RouterResult()
        result.success = True
        result.fallback_used = True
        result.model_used = "fallback-model"

        agent = _FallbackAwareAgent(result)

        with patch("backend.core.metrics.record_agent_fallback") as mock:
            await agent.process(_SimpleInput())

        mock.assert_called_once_with("fallback_test", "primary-model", "fallback-model")

    async def test_no_fallback_no_call(self) -> None:
        """Assert no fallback metric when fallback_used is False."""
        result = RouterResult()
        result.success = True
        result.fallback_used = False
        result.model_used = "primary-model"

        agent = _FallbackAwareAgent(result)

        with patch("backend.core.metrics.record_agent_fallback") as mock:
            await agent.process(_SimpleInput())

        mock.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: set_kill_switch_active
# ---------------------------------------------------------------------------


class TestSetKillSwitchActiveIntegration:
    """set_kill_switch_active fires during KillSwitch operations."""

    def test_activate_sets_active(self) -> None:
        ks = KillSwitch()

        with patch("live_trading.safety.set_kill_switch_active") as mock:
            ks.activate(reason="test")

        mock.assert_called_once_with(True)

    def test_arm_sets_inactive(self) -> None:
        ks = KillSwitch()
        ks.activate(reason="test")  # prime it

        with patch("live_trading.safety.set_kill_switch_active") as mock:
            ks.arm()

        mock.assert_called_once_with(False)

    def test_auto_trigger_sets_active_on_breach(self) -> None:
        ks = KillSwitch(max_drawdown_pct=15.0)

        with patch("live_trading.safety.set_kill_switch_active") as mock:
            tripped = ks.auto_trigger(20.0)

        assert tripped is True
        mock.assert_called_once_with(True)

    def test_auto_trigger_no_call_below_threshold(self) -> None:
        ks = KillSwitch(max_drawdown_pct=15.0)

        with patch("live_trading.safety.set_kill_switch_active") as mock:
            tripped = ks.auto_trigger(10.0)

        assert tripped is False
        mock.assert_not_called()

    def test_activate_respects_nx(self) -> None:
        """Second activate should NOT call the metric (NX prevents duplicate)."""
        ks = KillSwitch()
        ks.activate(reason="first")

        with patch("live_trading.safety.set_kill_switch_active") as mock:
            ks.activate(reason="second")

        mock.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: record_live_order
# ---------------------------------------------------------------------------


class TestRecordLiveOrderIntegration:
    """record_live_order fires during LiveTradingEngine.execute_signal()."""

    @pytest.fixture
    def engine(self):
        exchange = AsyncMock(spec=ExchangeConnector)
        exchange.exchange_name = "mock"
        exchange.is_connected = True
        exchange.connect = AsyncMock(return_value=True)
        exchange.create_order = AsyncMock(
            return_value=AsyncMock(
                id="ord_1",
                symbol="BTC/USDT",
                side="buy",
                type="market",
                quantity=0.01,
                price=50000.0,
                filled=0.01,
                remaining=0.0,
                status="closed",
            )
        )
        ks = KillSwitch(max_drawdown_pct=15.0)
        mm = ModeManager(TradingMode.SEMI)
        pg = PromotionGate(min_paper_trades=10, min_paper_days=5)
        eng = LiveTradingEngine(exchange, ks, mm, pg)
        eng.set_paper_record(10, 5)
        return eng

    async def test_success_records_status(self, engine) -> None:
        await engine.start()
        signal = {"symbol": "BTC/USDT", "side": "buy", "quantity": 0.01, "order_type": "market"}

        with patch("live_trading.engine.record_live_order") as mock:
            await engine.execute_signal(signal)

        mock.assert_called_once_with("closed")

    async def test_error_records_error(self, engine) -> None:
        engine.exchange.create_order = AsyncMock(side_effect=RuntimeError("exchange down"))
        await engine.start()
        signal = {"symbol": "BTC/USDT", "side": "buy", "quantity": 0.01}

        with patch("live_trading.engine.record_live_order") as mock:
            with pytest.raises(RuntimeError, match="exchange down"):
                await engine.execute_signal(signal)

        mock.assert_called_once_with("error")
