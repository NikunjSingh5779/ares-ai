import pytest
from unittest.mock import AsyncMock, MagicMock

from live_trading.engine import LiveTradingEngine
from live_trading.safety import TradingMode

@pytest.fixture
def mock_exchange():
    exchange = MagicMock()
    exchange.cancel_all_orders = AsyncMock(return_value=True)
    return exchange

@pytest.fixture
def engine(mock_exchange):
    from live_trading.safety import KillSwitch, ModeManager, PromotionGate
    
    engine = LiveTradingEngine(
        exchange=mock_exchange,
        kill_switch=KillSwitch(),
        mode_manager=ModeManager(),
        promotion_gate=PromotionGate()
    )
    # The default max_drawdown_pct in KillSwitch is 15.0 unless overridden
    # The requirement is to test the drawdown evaluation.
    engine.mode_manager.set_mode(TradingMode.AUTO)
    # Mocking is_connected
    engine._connected = True
    return engine

@pytest.mark.asyncio
async def test_kill_switch_triggers_on_excessive_drawdown(engine, mock_exchange):
    # Set a high drawdown that should trigger the kill switch
    # KillSwitch default is 15.0%. Let's pass 15.1%
    assert engine.mode == TradingMode.AUTO
    
    result = await engine.evaluate_drawdown(15.1, "BTC-USD")
    
    # Assert TradingMode reverted
    assert engine.mode == TradingMode.HUMAN_APPROVAL
    assert result is True
    
    # Assert exchange.cancel_all_orders called exactly once
    mock_exchange.cancel_all_orders.assert_called_once_with("BTC-USD")

@pytest.mark.asyncio
async def test_kill_switch_does_not_trigger_below_threshold(engine, mock_exchange):
    assert engine.mode == TradingMode.AUTO
    
    # 14.9% is below the 15.0% threshold
    result = await engine.evaluate_drawdown(14.9, "BTC-USD")
    
    assert engine.mode == TradingMode.AUTO
    assert result is False
    mock_exchange.cancel_all_orders.assert_not_called()
