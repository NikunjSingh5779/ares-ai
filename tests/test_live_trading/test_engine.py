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
from live_trading.exceptions import ExchangeConnectionError, PromotionGateError


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
        record = engine.paper_record
        assert record["trades"] == 10
        assert record["days"] == 5
        assert record["promotion"]["passed"] is True

    async def test_paper_record_not_promoted(self, engine) -> None:
        engine.set_paper_record(1, 1)
        assert not engine.paper_record["promotion"]["passed"]


class TestPreTradeChecks:
    """Safety gate evaluation order tests."""

    async def test_kill_switch_blocks(self, engine) -> None:
        engine.kill_switch.activate(reason="test")
        with pytest.raises(KillSwitchTrippedError):
            engine._raise_if_blocked(engine.check_pre_trade())

    async def test_promotion_gate_blocks(self, engine) -> None:
        engine.set_paper_record(1, 1)
        with pytest.raises(PromotionGateError):
            engine._raise_if_blocked(engine.check_pre_trade())

    async def test_exchange_disconnect_blocks(self, engine, mock_exchange) -> None:
        mock_exchange.is_connected = False
        with pytest.raises(ExchangeConnectionError):
            engine._raise_if_blocked(engine.check_pre_trade())

    async def test_all_checks_pass(self, engine) -> None:
        results = engine.check_pre_trade()
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

    async def test_execute_signal_records_audit_even_when_pending_approval(
        self, engine
    ) -> None:
        engine.mode_manager.set_mode(TradingMode.HUMAN_APPROVAL)
        await engine.start()
        signal = {"symbol": "BTC/USDT", "side": "buy", "quantity": 0.01}
        await engine.execute_signal(signal)
        assert engine.auditor.count() == 1
        entry = engine.auditor.recent(1)[0]
        assert entry.order_result["status"] == "pending_approval"
