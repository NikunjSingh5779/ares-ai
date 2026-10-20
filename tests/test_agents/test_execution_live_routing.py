from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.execution import ExecutionAgent, ExecutionInput
from backend.data.models import OHLCVData
from live_trading.engine import LiveTradingEngine
from live_trading.exchange.base import ExchangeOrder
from live_trading.safety import TradingMode
from paper_trading.engine import PaperTradingEngine


@pytest.fixture
def mock_paper_engine():
    engine = MagicMock(spec=PaperTradingEngine)
    engine.execute_signal.return_value = {
        "accepted": True,
        "position_id": "paper_pos_1",
        "closed_trade": None,
        "reversal": False,
    }
    return engine


@pytest.fixture
def mock_live_exchange():
    exchange = MagicMock()
    exchange.create_order = AsyncMock(
        return_value=ExchangeOrder(
            id="live_order_1",
            symbol="BTC-USD",
            side="buy",
            type="market",
            quantity=1.0,
            price=50000.0,
            status="open",
            filled=0.0,
            remaining=1.0,
            raw={},
        )
    )
    return exchange


@pytest.fixture
def mock_live_engine(mock_live_exchange):
    engine = MagicMock(spec=LiveTradingEngine)
    engine.exchange = mock_live_exchange
    engine.is_connected = True
    return engine


@pytest.fixture
def execution_input():
    return ExecutionInput(
        symbol="BTC-USD",
        candles=[
            OHLCVData(
                source="yahoo",
                symbol="BTC-USD",
                interval="1m",
                timestamp=datetime.now(),
                open=50000.0,
                high=50100.0,
                low=49900.0,
                close=50000.0,
                volume=10.0,
            )
        ],
        portfolio_value=100000.0,
        market_analyst_output={"direction": "long", "confidence": 90, "strategy_name": "test_strat"},
        risk_output={"approved": True, "stop_loss": 49000, "max_position_size": 1.0},
    )


@pytest.mark.asyncio
async def test_routes_to_paper_when_mode_is_not_auto(mock_paper_engine, mock_live_engine, execution_input):
    mock_live_engine.mode = TradingMode.HUMAN_APPROVAL

    agent = ExecutionAgent(engine=mock_paper_engine, live_engine=mock_live_engine)
    result = await agent.process(execution_input)

    assert result.executed is True
    assert "PAPER EXECUTED" in result.rationale
    mock_paper_engine.execute_signal.assert_called_once()
    mock_live_engine.exchange.create_order.assert_not_called()


@pytest.mark.asyncio
async def test_routes_to_paper_when_mode_auto_but_promotion_gate_failed(
    mock_paper_engine, mock_live_engine, execution_input
):
    mock_live_engine.mode = TradingMode.AUTO

    # Mock paper_record as async method returning dict
    from unittest.mock import AsyncMock

    mock_live_engine.paper_record = AsyncMock(return_value={"promotion": {"passed": False}})

    agent = ExecutionAgent(engine=mock_paper_engine, live_engine=mock_live_engine)
    result = await agent.process(execution_input)

    assert result.executed is True
    assert "PAPER EXECUTED" in result.rationale
    mock_paper_engine.execute_signal.assert_called_once()
    mock_live_engine.exchange.create_order.assert_not_called()


@pytest.mark.asyncio
async def test_routes_to_live_through_engine_when_enabled(
    mock_paper_engine, mock_live_engine, execution_input, monkeypatch
):
    from configs.settings import settings

    monkeypatch.setattr(settings, "live_trading_enabled", True)
    mock_live_engine.mode = TradingMode.AUTO
    mock_live_engine.is_running = True
    mock_live_engine.is_connected = True
    mock_live_engine.paper_record = AsyncMock(return_value={"promotion": {"passed": True}})
    mock_live_engine.execute_signal = AsyncMock(
        return_value={
            "accepted": True,
            "reason": "ok",
            "order": {"id": "live_order_1", "price": 50000.0},
        }
    )

    agent = ExecutionAgent(engine=mock_paper_engine, live_engine=mock_live_engine)
    result = await agent.process(execution_input)

    assert result.executed is True
    assert result.order_id == "live_order_1"
    assert "LIVE EXECUTED" in result.rationale
    mock_live_engine.execute_signal.assert_awaited_once()
    sent = mock_live_engine.execute_signal.await_args.kwargs
    assert sent["signal"]["symbol"] == "BTC-USD"
    assert sent["signal"]["side"] == "buy"
    # The agent must never bypass the engine's safety gates.
    mock_live_engine.exchange.create_order.assert_not_called()
    mock_paper_engine.execute_signal.assert_not_called()


@pytest.mark.asyncio
async def test_live_disabled_falls_back_to_paper(mock_paper_engine, mock_live_engine, execution_input, monkeypatch):
    from configs.settings import settings

    monkeypatch.setattr(settings, "live_trading_enabled", False)
    mock_live_engine.mode = TradingMode.AUTO
    mock_live_engine.is_running = True
    mock_live_engine.is_connected = True
    mock_live_engine.paper_record = AsyncMock(return_value={"promotion": {"passed": True}})
    mock_live_engine.execute_signal = AsyncMock()

    agent = ExecutionAgent(engine=mock_paper_engine, live_engine=mock_live_engine)
    result = await agent.process(execution_input)

    assert result.executed is True
    assert "PAPER EXECUTED" in result.rationale
    mock_live_engine.execute_signal.assert_not_awaited()
    mock_live_engine.exchange.create_order.assert_not_called()
    mock_paper_engine.execute_signal.assert_called_once()


@pytest.mark.asyncio
async def test_live_engine_rejection_is_reported(mock_paper_engine, mock_live_engine, execution_input, monkeypatch):
    from configs.settings import settings

    monkeypatch.setattr(settings, "live_trading_enabled", True)
    mock_live_engine.mode = TradingMode.AUTO
    mock_live_engine.is_running = True
    mock_live_engine.is_connected = True
    mock_live_engine.paper_record = AsyncMock(return_value={"promotion": {"passed": True}})
    mock_live_engine.execute_signal = AsyncMock(
        return_value={
            "accepted": False,
            "reason": "Kill switch active",
            "order": None,
        }
    )

    agent = ExecutionAgent(engine=mock_paper_engine, live_engine=mock_live_engine)
    result = await agent.process(execution_input)

    assert result.executed is False
    assert "Live trade not accepted" in result.rationale
    assert "Kill switch active" in result.rationale
    mock_paper_engine.execute_signal.assert_not_called()
