import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from agents.execution import ExecutionAgent, ExecutionInput
from live_trading.engine import LiveTradingEngine
from paper_trading.engine import PaperTradingEngine
from live_trading.safety import TradingMode
from live_trading.exchange.base import ExchangeOrder
from backend.data.models import OHLCVData

@pytest.fixture
def mock_paper_engine():
    engine = MagicMock(spec=PaperTradingEngine)
    engine.execute_signal.return_value = {
        "accepted": True,
        "position_id": "paper_pos_1",
        "closed_trade": None,
        "reversal": False
    }
    return engine

@pytest.fixture
def mock_live_exchange():
    exchange = MagicMock()
    exchange.create_order = AsyncMock(return_value=ExchangeOrder(
        id="live_order_1",
        symbol="BTC-USD",
        side="buy",
        type="market",
        quantity=1.0,
        price=50000.0,
        status="open",
        filled=0.0,
        remaining=1.0,
        raw={}
    ))
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
        candles=[OHLCVData(
            source="yahoo",
            symbol="BTC-USD",
            interval="1m",
            timestamp=datetime.now(),
            open="50000",
            high="50100",
            low="49900",
            close="50000",
            volume="10"
        )],
        portfolio_value=100000.0,
        market_analyst_output={"direction": "long", "confidence": 90, "strategy_name": "test_strat"},
        risk_output={"approved": True, "stop_loss": 49000, "max_position_size": 1.0}
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
async def test_routes_to_paper_when_mode_auto_but_promotion_gate_failed(mock_paper_engine, mock_live_engine, execution_input):
    mock_live_engine.mode = TradingMode.AUTO
    
    # Mock paper_record as property returning dict
    mock_live_engine.paper_record = {"promotion": {"passed": False}}
    
    agent = ExecutionAgent(engine=mock_paper_engine, live_engine=mock_live_engine)
    result = await agent.process(execution_input)
    
    assert result.executed is True
    assert "PAPER EXECUTED" in result.rationale
    mock_paper_engine.execute_signal.assert_called_once()
    mock_live_engine.exchange.create_order.assert_not_called()

@pytest.mark.asyncio
async def test_routes_to_live_when_mode_auto_and_promotion_gate_passed(mock_paper_engine, mock_live_engine, execution_input):
    mock_live_engine.mode = TradingMode.AUTO
    mock_live_engine.paper_record = {"promotion": {"passed": True}}
    
    agent = ExecutionAgent(engine=mock_paper_engine, live_engine=mock_live_engine)
    result = await agent.process(execution_input)
    
    assert result.executed is True
    assert "LIVE EXECUTED" in result.rationale
    mock_live_engine.exchange.create_order.assert_called_once_with(
        symbol="BTC-USD",
        side="buy",
        quantity=1.0,
        order_type="market"
    )
    mock_paper_engine.execute_signal.assert_not_called()
