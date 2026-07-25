"""Tests for the PaperTradingWorker."""

import asyncio
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.data.ingestor import MarketDataIngestor
from backend.data.models import MarketDataResult, OHLCVData
from paper_trading.engine import PaperTradingEngine
from paper_trading.worker import PaperTradingWorker


@pytest.fixture
def engine():
    eng = PaperTradingEngine(initial_capital=100000.0)
    # Add a dummy position
    eng.execute_signal("BTC-USD", "long", 1.0, 50000.0, stop_loss=48000.0, take_profit=55000.0)
    return eng


@pytest.fixture
def ingestor():
    mock_ingestor = AsyncMock(spec=MarketDataIngestor)
    from datetime import datetime

    candle = OHLCVData(
        symbol="BTC-USD",
        source="yahoo",
        interval="1m",
        timestamp=datetime.now(UTC),
        open=50000.0,
        high=56000.0,  # High enough to trigger TP
        low=49000.0,
        close=55000.0,
        volume=100.0,
    )
    mock_ingestor.ingest_batch.return_value = [
        MarketDataResult(symbol="BTC-USD", source="yahoo", interval="1m", candles=[candle])
    ]
    return mock_ingestor


@pytest.fixture
def session_factory():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.execute.return_value.scalar.return_value = 1  # Dummy ID
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    return mock_factory


@pytest.mark.asyncio
async def test_worker_tick_closes_trade_and_persists(engine, ingestor, session_factory):
    worker = PaperTradingWorker(engine, ingestor, session_factory, poll_interval_seconds=1)

    assert len(engine._positions) == 1

    # Tick should fetch candle, close position, and update DB
    await worker._tick()

    assert len(engine._positions) == 0
    assert len(engine._closed_trades) == 1
    assert engine._closed_trades[0].exit_reason == "take_profit"

    ingestor.ingest_batch.assert_called_once_with(symbols=["BTC-USD"], source="yahoo", interval="1m", limit=1)

    # Check DB was updated
    session = session_factory.return_value.__aenter__.return_value
    assert session.execute.call_count >= 5  # get acc, get port, update pos, update port, insert order
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_worker_start_stop(engine, ingestor, session_factory):
    worker = PaperTradingWorker(engine, ingestor, session_factory, poll_interval_seconds=1)

    # Mock _tick so it just returns immediately
    worker._tick = AsyncMock()  # type: ignore[method-assign]

    worker.start()
    assert worker._running is True
    assert worker._task is not None

    # Let event loop run slightly so task starts
    await asyncio.sleep(0.01)

    await worker.stop()
    assert worker._running is False
    assert worker._task is None
