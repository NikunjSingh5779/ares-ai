"""Tests for the LiveTradingEngine including safety gate integration.

Uses a mock exchange connector to avoid any network dependency.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from live_trading import (
    ExchangeConnector,
    KillSwitch,
    KillSwitchTrippedError,
    LiveTradingEngine,
    ModeManager,
    PromotionGate,
    TradingMode,
)
from live_trading.exceptions import ExchangeConnectionError, ModeError, PromotionGateError
from live_trading.safety import SafetyCheckResult


@pytest.fixture
def mock_exchange():
    """Create a mock exchange connector."""
    exchange = AsyncMock(spec=ExchangeConnector)
    exchange.exchange_name = "mock_exchange"
    exchange.is_connected = True
    exchange.connect = AsyncMock(return_value=True)
    exchange.disconnect = AsyncMock()
    exchange.create_order = AsyncMock(
        return_value=AsyncMock(
            id="order_123",
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
    return exchange


@pytest.fixture
def engine(mock_exchange):
    """Create a LiveTradingEngine with mocked dependencies."""
    ks = KillSwitch(max_drawdown_pct=15.0)
    mm = ModeManager(TradingMode.SEMI)  # Semi mode so we don't need approval
    pg = PromotionGate(min_paper_trades=10, min_paper_days=5)
    engine = LiveTradingEngine(mock_exchange, ks, mm, pg)
    engine.set_paper_record(10, 5)  # Meet promotion requirements
    return engine


class TestEngineLifecycle:
    """Engine start/stop lifecycle tests."""

    async def test_start_connects_and_runs(self, engine, mock_exchange) -> None:
        result = await engine.start()
        assert result is True
        assert engine.is_running
        mock_exchange.connect.assert_awaited_once()

    async def test_stop_disconnects(self, engine, mock_exchange) -> None:
        await engine.start()
        await engine.stop()
        assert not engine.is_running
        mock_exchange.disconnect.assert_awaited_once()

    async def test_start_returns_false_on_failure(self, engine, mock_exchange) -> None:
        mock_exchange.connect = AsyncMock(return_value=False)
        result = await engine.start()
        assert result is False
        assert not engine.is_running


class TestEngineProperties:
    """Engine property tests."""

    async def test_is_connected_delegates_to_exchange(self, engine, mock_exchange) -> None:
        assert engine.is_connected == mock_exchange.is_connected

    async def test_mode_returns_mode_manager_mode(self, engine) -> None:
        assert engine.mode == TradingMode.SEMI

    async def test_paper_record(self, engine) -> None:
        record = await engine.paper_record()
        assert record["trades"] == 10
        assert record["days"] == 5
        assert record["promotion"]["passed"] is True

    async def test_paper_record_not_promoted(self, engine) -> None:
        engine.set_paper_record(1, 1)
        record = await engine.paper_record()
        assert not record["promotion"]["passed"]


class TestPreTradeChecks:
    """Safety gate evaluation order tests."""

    async def test_kill_switch_blocks(self, engine) -> None:
        engine.kill_switch.activate(reason="test")
        with pytest.raises(KillSwitchTrippedError):
            engine._raise_if_blocked(await engine.check_pre_trade())

    async def test_promotion_gate_blocks(self, engine) -> None:
        engine.set_paper_record(1, 1)
        with pytest.raises(PromotionGateError):
            engine._raise_if_blocked(await engine.check_pre_trade())

    async def test_exchange_disconnect_blocks(self, engine, mock_exchange) -> None:
        mock_exchange.is_connected = False
        with pytest.raises(ExchangeConnectionError):
            engine._raise_if_blocked(await engine.check_pre_trade())

    async def test_all_checks_pass(self, engine) -> None:
        results = await engine.check_pre_trade()
        assert all(r.passed for r in results)


class TestExecuteSignal:
    """Signal execution tests."""

    async def test_execute_signal_success(self, engine) -> None:
        await engine.start()
        signal = {"symbol": "BTC/USDT", "side": "buy", "quantity": 0.01, "order_type": "market"}
        result = await engine.execute_signal(signal)
        assert result["accepted"] is True
        assert result["order"]["id"] == "order_123"

    async def test_execute_signal_with_agent_chain(self, engine) -> None:
        await engine.start()
        signal = {"symbol": "ETH/USDT", "side": "sell", "quantity": 0.1}
        agent_chain = [
            {"agent": "market_analyst", "confidence": 0.9, "direction": "sell"},
            {"agent": "quant", "confidence": 0.85, "direction": "sell"},
        ]
        result = await engine.execute_signal(signal, agent_chain=agent_chain)
        assert result["accepted"] is True

    async def test_execute_signal_requires_approval_in_human_mode(self, engine) -> None:
        engine.mode_manager.set_mode(TradingMode.HUMAN_APPROVAL)
        await engine.start()
        signal = {"symbol": "BTC/USDT", "side": "buy", "quantity": 0.01}
        result = await engine.execute_signal(signal)
        assert result["accepted"] is False
        assert "approval" in result["reason"].lower()

    async def test_execute_signal_with_approval_in_human_mode(self, engine) -> None:
        engine.mode_manager.set_mode(TradingMode.HUMAN_APPROVAL)
        await engine.start()
        signal = {"symbol": "BTC/USDT", "side": "buy", "quantity": 0.01}
        result = await engine.execute_signal(signal, approval_id="human_approval_123")
        assert result["accepted"] is True

    async def test_execute_signal_kill_switch_blocks(self, engine) -> None:
        engine.kill_switch.activate(reason="emergency")
        signal = {"symbol": "BTC/USDT", "side": "buy", "quantity": 0.01}
        with pytest.raises(KillSwitchTrippedError):
            await engine.execute_signal(signal)

    async def test_execute_signal_promotion_fails(self, engine) -> None:
        engine.set_paper_record(1, 1)
        signal = {"symbol": "BTC/USDT", "side": "buy", "quantity": 0.01}
        with pytest.raises(PromotionGateError):
            await engine.execute_signal(signal)

    async def test_execute_signal_records_audit(self, engine) -> None:
        await engine.start()
        signal = {"symbol": "BTC/USDT", "side": "buy", "quantity": 0.01}
        await engine.execute_signal(signal)
        assert engine.auditor.count() == 1

    async def test_execute_signal_records_audit_even_when_pending_approval(self, engine) -> None:
        engine.mode_manager.set_mode(TradingMode.HUMAN_APPROVAL)
        await engine.start()
        signal = {"symbol": "BTC/USDT", "side": "buy", "quantity": 0.01}
        await engine.execute_signal(signal)
        assert engine.auditor.count() == 1
        entry = engine.auditor.recent(1)[0]
        assert entry.order_result["status"] == "pending_approval"


class TestRaiseIfBlockedTypedRouting:
    """`_raise_if_blocked` must branch on SafetyCheckResult.code, not on
    substrings of `reason`. These tests lock in that contract so a future
    rewording of a reason message can never silently disable a gate.
    """

    def test_kill_switch_code_raises_kill_switch_error(self, engine) -> None:
        with pytest.raises(KillSwitchTrippedError):
            engine._raise_if_blocked([SafetyCheckResult(passed=False, reason="anything", code="kill_switch")])

    def test_promotion_gate_code_raises_promotion_gate_error(self, engine) -> None:
        with pytest.raises(PromotionGateError):
            engine._raise_if_blocked([SafetyCheckResult(passed=False, reason="anything", code="promotion_gate")])

    def test_exchange_code_raises_exchange_connection_error(self, engine) -> None:
        with pytest.raises(ExchangeConnectionError):
            engine._raise_if_blocked([SafetyCheckResult(passed=False, reason="anything", code="exchange")])

    def test_mode_code_raises_mode_error(self, engine) -> None:
        with pytest.raises(ModeError):
            engine._raise_if_blocked([SafetyCheckResult(passed=False, reason="anything", code="mode")])

    def test_reworded_reason_text_still_raises(self, engine) -> None:
        """The core regression case: even if `reason` text is completely
        reworded (no longer containing 'Kill switch' etc.), the gate must
        still raise because it is keyed off `code`, not text.
        """
        with pytest.raises(KillSwitchTrippedError):
            engine._raise_if_blocked(
                [SafetyCheckResult(passed=False, reason="Trading halted (see incident #4471)", code="kill_switch")]
            )

    def test_unrecognized_code_fails_closed_not_silently_approved(self, engine) -> None:
        """If a failing check ever carries a code with no mapped exception,
        the engine must still raise (fail closed) rather than silently
        falling through to order placement.
        """
        with pytest.raises(RuntimeError):
            engine._raise_if_blocked([SafetyCheckResult(passed=False, reason="unmapped failure", code="ok")])

    def test_passing_results_do_not_raise(self, engine) -> None:
        engine._raise_if_blocked(
            [
                SafetyCheckResult(passed=True, code="kill_switch"),
                SafetyCheckResult(passed=True, code="mode"),
                SafetyCheckResult(passed=True, code="promotion_gate"),
                SafetyCheckResult(passed=True, code="exchange"),
            ]
        )  # should not raise
