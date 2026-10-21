"""Tests for the PaperTradingWorker."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.data.ingestor import MarketDataIngestor
from backend.data.models import MarketDataResult, OHLCVData
from paper_trading.engine import ClosedTrade, PaperTradingEngine
from paper_trading.ledger import PaperTradingLedger
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
async def test_worker_marks_open_position_on_every_tick(engine, ingestor, session_factory):
    """A non-triggering candle still updates equity and drawdown marks."""
    from datetime import datetime

    candle = OHLCVData(
        symbol="BTC-USD",
        source="yahoo",
        interval="1m",
        timestamp=datetime.now(UTC),
        open=50000.0,
        high=51000.0,
        low=49000.0,
        close=50500.0,
        volume=100.0,
    )
    ingestor.ingest_batch.return_value = [
        MarketDataResult(symbol="BTC-USD", source="yahoo", interval="1m", candles=[candle])
    ]
    worker = PaperTradingWorker(engine, ingestor, session_factory, poll_interval_seconds=1)

    await worker._tick()

    assert len(engine._positions) == 1
    summary = engine.get_summary()
    assert summary.total_pnl == pytest.approx(500.0)
    assert summary.equity == pytest.approx(100500.0)


@pytest.mark.asyncio
async def test_persist_closed_trade_writes_history_and_engine_snapshot(ingestor):
    """SL/TP closures must be countable and use buy/sell in trade_history."""
    engine = PaperTradingEngine(initial_capital=100000.0)
    result = engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
    trade = engine.close_position(result["position_id"], 55000.0)
    assert trade is not None

    session = _CapturingSession()
    worker = PaperTradingWorker(engine, ingestor, _CapturingSessionFactory(session))  # type: ignore[arg-type]
    await worker._persist_closed_trades([trade])

    history = [params for sql, params in session.calls if "INSERT INTO trade_history" in sql]
    assert len(history) == 1
    assert history[0]["side"] == "buy"
    assert history[0]["pnl"] == pytest.approx(5000.0)

    portfolio = [params for sql, params in session.calls if "UPDATE portfolio" in sql]
    assert len(portfolio) == 1
    assert portfolio[0]["total_value"] == pytest.approx(105000.0)
    assert portfolio[0]["realized_pnl"] == pytest.approx(5000.0)
    assert portfolio[0]["max_drawdown_pct"] == pytest.approx(0.0)
    assert session.committed is True

    # Guard the exact schema mismatches found during review: positions has no
    # realized_pnl column, and orders has no strategy_name/reason columns.
    positions_sql = next(sql for sql, _ in session.calls if "UPDATE positions" in sql)
    assert re.search(r"\brealized_pnl\b", positions_sql) is None
    orders_sql = next(sql for sql, _ in session.calls if "INSERT INTO orders" in sql)
    assert "agent_rationale" in orders_sql
    assert "strategy_name" not in orders_sql


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


class _MockDBSession:
    """Simple async context manager that simulates a DB session for testing."""

    def __init__(self) -> None:
        self.execute = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


class _FailingDBSession:
    """Simulates a DB session that raises on __aenter__."""

    async def __aenter__(self):
        raise RuntimeError("DB is down")

    async def __aexit__(self, *args: object) -> None:
        pass


class TestWorkerEdgeCases:
    """Cover the remaining uncovered lines in PaperTradingWorker."""

    @pytest.mark.asyncio
    async def test_start_when_already_running(self, engine, ingestor, session_factory):
        """start() returns early when already running (line 50)."""
        worker = PaperTradingWorker(engine, ingestor, session_factory)
        worker._tick = AsyncMock()  # type: ignore[method-assign]
        worker.start()
        worker.start()  # Should return at line 50 (no-op)
        assert worker._running is True
        assert worker._task is not None
        await worker.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, engine, ingestor, session_factory):
        """stop() returns early when not running (line 58)."""
        worker = PaperTradingWorker(engine, ingestor, session_factory)
        await worker.stop()  # Should return at line 58 (no-op)
        assert worker._running is False
        assert worker._task is None

    @pytest.mark.asyncio
    async def test_loop_breaks_on_cancelled_error(self, engine, ingestor, session_factory):
        """_loop catches CancelledError and breaks (lines 74-75)."""
        worker = PaperTradingWorker(engine, ingestor, session_factory, poll_interval_seconds=999)
        worker._tick = AsyncMock(side_effect=asyncio.CancelledError())  # type: ignore[method-assign]
        worker.start()
        await asyncio.wait_for(worker._task, timeout=5)
        assert worker._task.done()

    @pytest.mark.asyncio
    async def test_loop_logs_exception(self, engine, ingestor, session_factory):
        """_loop catches generic exceptions and logs them (lines 76-77)."""
        worker = PaperTradingWorker(engine, ingestor, session_factory, poll_interval_seconds=0.01)
        worker._tick = AsyncMock(side_effect=ValueError("test error"))  # type: ignore[method-assign]
        worker.start()
        await asyncio.sleep(0.05)
        assert worker._running is True
        await worker.stop()

    @pytest.mark.asyncio
    async def test_tick_skips_symbol_with_no_candles(self, engine, ingestor, session_factory):
        """_tick continues when a result has no candles (line 105)."""
        worker = PaperTradingWorker(engine, ingestor, session_factory)
        ingestor.ingest_batch.return_value = [
            MarketDataResult(symbol="BTC-USD", source="yahoo", interval="1m", candles=[])
        ]
        await worker._tick()
        # Position should still be open (no SL/TP to evaluate)
        assert len(engine._positions) == 1

    @pytest.mark.asyncio
    async def test_persist_no_account_found(self, engine, ingestor):
        """_persist_closed_trades warns and returns when no paper account (lines 129-130)."""
        from datetime import datetime
        from unittest.mock import patch

        session = _MockDBSession()
        # Explicit MagicMock — AsyncMock's auto-created children are AsyncMock,
        # whose scalar() returns a coroutine, not the configured value.
        result_mock = MagicMock()
        result_mock.scalar.return_value = None
        session.execute.return_value = result_mock

        worker = PaperTradingWorker(engine, ingestor, lambda: session)  # type: ignore[arg-type]
        trade = ClosedTrade(
            symbol="BTC-USD",
            side="long",
            quantity=1.0,
            entry_price=50000.0,
            exit_price=55000.0,
            entry_at=datetime.now(UTC),
            exit_at=datetime.now(UTC),
            pnl=5000.0,
            pnl_pct=10.0,
            exit_reason="take_profit",
        )
        with patch("paper_trading.worker.logger") as mock_logger:
            await worker._persist_closed_trades([trade])
            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_no_portfolio_found(self, engine, ingestor, session_factory):
        """_persist_closed_trades returns early when no portfolio (line 140)."""
        from datetime import datetime

        mock_result_account = MagicMock()
        mock_result_account.scalar.return_value = 1

        mock_result_portfolio = MagicMock()
        mock_result_portfolio.scalar.return_value = None

        session = session_factory.return_value.__aenter__.return_value
        session.execute.side_effect = [mock_result_account, mock_result_portfolio]

        worker = PaperTradingWorker(engine, ingestor, session_factory)
        trade = ClosedTrade(
            symbol="BTC-USD",
            side="long",
            quantity=1.0,
            entry_price=50000.0,
            exit_price=55000.0,
            entry_at=datetime.now(UTC),
            exit_at=datetime.now(UTC),
            pnl=5000.0,
            pnl_pct=10.0,
            exit_reason="take_profit",
        )
        await worker._persist_closed_trades([trade])

    @pytest.mark.asyncio
    async def test_persist_exception_logged(self, engine, ingestor, session_factory):
        """_persist_closed_trades catches and logs DB exceptions (lines 210-211)."""
        from datetime import datetime

        # Make the session __aenter__ raise an exception
        session_factory.return_value.__aenter__.side_effect = RuntimeError("DB is down")

        worker = PaperTradingWorker(engine, ingestor, session_factory)
        trade = ClosedTrade(
            symbol="BTC-USD",
            side="long",
            quantity=1.0,
            entry_price=50000.0,
            exit_price=55000.0,
            entry_at=datetime.now(UTC),
            exit_at=datetime.now(UTC),
            pnl=5000.0,
            pnl_pct=10.0,
            exit_reason="take_profit",
        )
        # Should not raise — exception is caught and logged
        await worker._persist_closed_trades([trade])


class _CapturingResult:
    def __init__(self, value: str = "fake-id") -> None:
        self._value = value

    def scalar(self) -> str:
        return self._value


class _CapturingSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.committed = False

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _CapturingResult:
        self.calls.append((str(statement), params or {}))
        return _CapturingResult()

    async def commit(self) -> None:
        self.committed = True


class _CapturingSessionContext:
    def __init__(self, session: _CapturingSession) -> None:
        self._session = session

    async def __aenter__(self) -> _CapturingSession:
        return self._session

    async def __aexit__(self, *args: object) -> None:
        return None


class _CapturingSessionFactory:
    def __init__(self, session: _CapturingSession) -> None:
        self._session = session

    def __call__(self) -> _CapturingSessionContext:
        return _CapturingSessionContext(self._session)


@pytest.mark.asyncio
async def test_worker_delegates_candle_processing_to_ledger(engine, ingestor, session_factory):
    """When a ledger is wired, the worker must not take the raw-SQL path twice."""
    ledger = MagicMock(spec=PaperTradingLedger)
    ledger.refresh = AsyncMock(return_value=True)
    ledger.process_candle = AsyncMock(return_value=[])
    worker = PaperTradingWorker(engine, ingestor, session_factory, poll_interval_seconds=1, ledger=ledger)

    await worker._tick()

    ledger.refresh.assert_awaited_once()
    ledger.process_candle.assert_awaited_once_with(
        symbol="BTC-USD",
        high=56000.0,
        low=49000.0,
        close=55000.0,
    )
    session = session_factory.return_value.__aenter__.return_value
    session.execute.assert_not_called()
