"""Paper-only default: the live engine must refuse to start or trade.

These tests deliberately disable LIVE_TRADING_ENABLED even though the
package-wide test fixture enables it for live-mechanics tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from configs.settings import settings
from live_trading import (
    ExchangeConnector,
    KillSwitch,
    LiveTradingEngine,
    ModeManager,
    PromotionGate,
    TradingMode,
)


@pytest.fixture
def paper_only_engine() -> LiveTradingEngine:
    exchange = AsyncMock(spec=ExchangeConnector)
    exchange.exchange_name = "mock_exchange"
    exchange.is_connected = True
    exchange.connect = AsyncMock(return_value=True)
    exchange.create_order = AsyncMock()
    return LiveTradingEngine(
        exchange,
        KillSwitch(max_drawdown_pct=15.0),
        ModeManager(TradingMode.SEMI),
        PromotionGate(min_paper_trades=1, min_paper_days=0),
    )


@pytest.mark.asyncio
async def test_start_refuses_when_live_trading_disabled(paper_only_engine, monkeypatch) -> None:
    monkeypatch.setattr(settings, "live_trading_enabled", False)

    started = await paper_only_engine.start()

    assert started is False
    assert paper_only_engine.is_running is False
    paper_only_engine.exchange.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_signal_refuses_when_live_trading_disabled(paper_only_engine, monkeypatch) -> None:
    monkeypatch.setattr(settings, "live_trading_enabled", False)

    result = await paper_only_engine.execute_signal(
        signal={"symbol": "BTC-USD", "side": "buy", "quantity": 1.0, "order_type": "market"}
    )

    assert result["accepted"] is False
    assert result["order"] is None
    assert "paper-only" in result["reason"].lower()
    paper_only_engine.exchange.create_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_blocked_live_attempt_is_audited(paper_only_engine, monkeypatch) -> None:
    """A paper-only refusal must leave an audit trail, not just a return value."""
    monkeypatch.setattr(settings, "live_trading_enabled", False)

    await paper_only_engine.execute_signal(
        signal={"symbol": "BTC-USD", "side": "buy", "quantity": 1.0, "order_type": "market"},
        agent_chain=[{"agent": "risk", "approved": True}],
        risk_checks=[{"check": "drawdown", "passed": True}],
    )

    entries = paper_only_engine.auditor.recent()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.order_result is not None
    assert entry.order_result["status"] == "blocked_paper_only"
    assert entry.order_intent["symbol"] == "BTC-USD"
    assert entry.agent_chain == [{"agent": "risk", "approved": True}]
    assert entry.risk_checks == [{"check": "drawdown", "passed": True}]
    paper_only_engine.exchange.create_order.assert_not_awaited()
