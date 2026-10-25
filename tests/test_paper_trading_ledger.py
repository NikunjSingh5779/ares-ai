"""Tests for the durable paper-trading ledger and its repository.

These tests use a small fake async session instead of PostgreSQL so they stay
deterministic and run in CI. The SQL is inspected at the parameter boundary;
the real database round-trip is verified manually against PostgreSQL 16.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from paper_trading.engine import ClosedTrade, PaperTradingEngine
from paper_trading.ledger import PaperTradingLedger
from paper_trading.repository import (
    PAPER_LEDGER_WRITER_LOCK_KEY,
    PaperLedgerBusyError,
    PaperLedgerError,
    PaperLedgerRepository,
    PaperOrderConflictError,
)


class _WriterLockSpy:
    """Records writer-lock entry/exit order around the ledger cycle."""

    def __init__(self) -> None:
        self.entries = 0
        self.exits = 0
        self.events: list[str] = []

    @asynccontextmanager
    async def __call__(self, *, timeout_seconds: float = 10.0) -> AsyncIterator[None]:
        self.entries += 1
        self.events.append("lock_enter")
        try:
            yield
        finally:
            self.exits += 1
            self.events.append("lock_exit")


class _FakeResult:
    def __init__(self, row: dict[str, Any] | None = None, rows: list[dict[str, Any]] | None = None) -> None:
        self._row = row
        self._rows = rows or []

    def mappings(self) -> _FakeResult:
        return self

    def first(self) -> dict[str, Any] | None:
        return self._row

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    def scalar(self) -> Any:
        if self._row is None:
            return None
        return next(iter(self._row.values()), None)


class _FakeSession:
    def __init__(self, results: list[_FakeResult] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.committed = False
        self.rolled_back = False
        self.commit_error: Exception | None = None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        self.calls.append((str(statement), params or {}))
        if self.results:
            return self.results.pop(0)
        return _FakeResult()

    async def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> _FakeSessionContext:
        return _FakeSessionContext(self._session)


def _portfolio_row() -> dict[str, Any]:
    return {
        "account_id": "account-1",
        "portfolio_id": "portfolio-1",
        "initial_capital": 100000.0,
        "cash_balance": 50000.0,
        "equity_curve": [100000.0, 101000.0],
    }


def _position_row() -> dict[str, Any]:
    return {
        "id": "position-1",
        "symbol": "BTC-USD",
        "side": "long",
        "quantity": 1.0,
        "entry_price": 50000.0,
        "current_price": 52000.0,
        "stop_loss": 48000.0,
        "take_profit": 55000.0,
        "strategy_name": "trend",
        "opened_at": datetime(2026, 1, 1, tzinfo=UTC),
        "entry_commission": 50.0,
        "margin": 0.0,
    }


def _trade_row() -> dict[str, Any]:
    return {
        "symbol": "ETH-USD",
        "position_side": "short",
        "side": "sell",
        "quantity": 2.0,
        "entry_price": 3000.0,
        "exit_price": 2900.0,
        "entry_at": datetime(2026, 1, 1, tzinfo=UTC),
        "exit_at": datetime(2026, 1, 2, tzinfo=UTC),
        "pnl": 200.0,
        "pnl_pct": 3.33,
        "strategy_name": "mean_reversion",
        "entry_commission": 6.0,
        "exit_commission": 5.8,
        "exit_reason": "take_profit",
    }


class TestPaperLedgerRepositoryHydration:
    async def test_hydrates_open_positions_closed_trades_and_curve(self) -> None:
        session = _FakeSession(
            [
                _FakeResult(row=_portfolio_row()),
                _FakeResult(rows=[_position_row()]),
                _FakeResult(rows=[_trade_row()]),
            ]
        )
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]
        engine = PaperTradingEngine(initial_capital=1.0)

        assert await repository.hydrate(engine) is True

        summary = engine.get_summary()
        assert summary.initial_capital == 100000.0
        assert summary.cash == 50000.0
        assert summary.open_positions == 1
        assert summary.total_trades == 1
        assert engine.get_last_prices()["BTC-USD"] == 52000.0

        position = engine.get_open_positions()[0]
        assert position.side == "long"
        assert position.entry_commission == 50.0
        assert position.entry_at == datetime(2026, 1, 1, tzinfo=UTC)

        trade = engine.get_closed_trades()[0]
        assert trade.side == "short"
        assert trade.exit_reason == "take_profit"
        assert trade.exit_commission == 5.8
        assert engine.get_equity_curve()[-1] == pytest.approx(102000.0)

    async def test_returns_false_when_paper_account_is_not_seeded(self) -> None:
        session = _FakeSession([_FakeResult(row=None)])
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]
        engine = PaperTradingEngine()

        assert await repository.hydrate(engine) is False
        assert engine.get_open_positions() == []

    async def test_parses_equity_curve_json_string(self) -> None:
        row = _portfolio_row()
        row["equity_curve"] = json.dumps([100000.0, 99000.0, 101000.0])
        session = _FakeSession(
            [
                _FakeResult(row=row),
                _FakeResult(rows=[]),
                _FakeResult(rows=[]),
            ]
        )
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]
        engine = PaperTradingEngine()

        assert await repository.hydrate(engine) is True
        assert engine.get_equity_curve()[:3] == [100000.0, 99000.0, 101000.0]

    async def test_wraps_database_errors(self) -> None:
        session = _FakeSession([])
        session.execute = AsyncMock(side_effect=RuntimeError("database down"))  # type: ignore[method-assign]
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]

        with pytest.raises(PaperLedgerError, match="hydrate"):
            await repository.hydrate(PaperTradingEngine())


class TestPaperOrderIdempotency:
    async def test_client_order_id_exists(self) -> None:
        session = _FakeSession([_FakeResult(row={"exists": 1})])
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]

        assert await repository.client_order_id_exists("client-1") is True

    async def test_client_order_id_is_absent(self) -> None:
        session = _FakeSession([_FakeResult(row=None)])
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]

        assert await repository.client_order_id_exists("client-1") is False

    async def test_duplicate_client_order_id_maps_to_conflict(self) -> None:
        session = _FakeSession([_FakeResult(row=_portfolio_row())])
        session.commit_error = IntegrityError(
            "INSERT INTO orders",
            {},
            Exception("duplicate key value violates unique constraint uq_orders_client_order_id"),
        )
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]

        with pytest.raises(PaperOrderConflictError, match="already been used"):
            await repository.persist(PaperTradingEngine(), client_order_id="client-1")


class TestPaperLedgerRepositoryPersistence:
    async def test_persists_position_history_orders_and_portfolio_atomically(self) -> None:
        session = _FakeSession([_FakeResult(row=_portfolio_row())])
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]
        engine = PaperTradingEngine(initial_capital=100000.0)
        result = engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        assert result["accepted"] is True
        position_id = result["position_id"]
        engine.mark_to_market("BTC-USD", 51000.0)

        closed = ClosedTrade(
            symbol="ETH-USD",
            side="short",
            quantity=2.0,
            entry_price=3000.0,
            exit_price=2900.0,
            entry_at=datetime(2026, 1, 1, tzinfo=UTC),
            exit_at=datetime(2026, 1, 2, tzinfo=UTC),
            pnl=200.0,
            pnl_pct=3.33,
            exit_reason="take_profit",
            strategy_name="mean_reversion",
            entry_commission=6.0,
            exit_commission=5.8,
            position_id="closed-position-1",
        )

        assert (
            await repository.persist(
                engine,
                closed_trades=[closed],
                entry_position_ids=[position_id],
                client_order_id="client-1",
            )
            is True
        )
        assert session.committed is True

        statements = [sql for sql, _ in session.calls]
        assert any("INSERT INTO positions" in sql for sql in statements)
        assert sum("INSERT INTO orders" in sql for sql in statements) == 2
        assert any("INSERT INTO trade_history" in sql for sql in statements)
        assert any("UPDATE portfolio" in sql for sql in statements)

        position_params = next(params for sql, params in session.calls if "INSERT INTO positions" in sql)
        assert position_params["side"] == "long"
        assert position_params["entry_commission"] >= 0.0

        entry_order_params = next(
            params
            for sql, params in session.calls
            if "INSERT INTO orders" in sql and params["client_order_id"] == "client-1"
        )
        assert entry_order_params["symbol"] == "BTC-USD"
        exit_order_params = next(
            params for sql, params in session.calls if "INSERT INTO orders" in sql and params["client_order_id"] is None
        )
        assert exit_order_params["symbol"] == "ETH-USD"

        trade_params = next(params for sql, params in session.calls if "INSERT INTO trade_history" in sql)
        assert trade_params["position_side"] == "short"
        assert trade_params["exit_reason"] == "take_profit"
        assert trade_params["entry_commission"] == 6.0

        portfolio_params = next(params for sql, params in session.calls if "UPDATE portfolio" in sql)
        curve = json.loads(portfolio_params["equity_curve"])
        assert curve[-1] == pytest.approx(engine.get_summary().equity)
        assert portfolio_params["margin_used"] == 0.0

    async def test_returns_false_without_seeded_account(self) -> None:
        session = _FakeSession([_FakeResult(row=None)])
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]

        assert await repository.persist(PaperTradingEngine()) is False
        assert session.committed is False

    async def test_wraps_commit_failures(self) -> None:
        session = _FakeSession([_FakeResult(row=_portfolio_row())])
        session.commit_error = RuntimeError("commit failed")
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]

        with pytest.raises(PaperLedgerError, match="persist"):
            await repository.persist(PaperTradingEngine())


class TestPaperLedgerRepositoryWriterLock:
    """The cross-process advisory lock that serializes API, worker, and runner."""

    async def test_acquires_and_releases_around_the_body(self) -> None:
        session = _FakeSession([_FakeResult(row={"locked": True})])
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]

        async with repository.writer_lock(timeout_seconds=1.0):
            assert "pg_try_advisory_xact_lock" in session.calls[0][0]
            assert session.calls[0][1]["key"] == PAPER_LEDGER_WRITER_LOCK_KEY
            assert session.rolled_back is False

        # The transaction-scoped lock dies with the rollback, so it cannot
        # leak onto a pooled connection.
        assert session.rolled_back is True

    async def test_retries_until_the_lock_is_granted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("paper_trading.repository.WRITER_LOCK_POLL_INTERVAL_SECONDS", 0.0)
        session = _FakeSession([_FakeResult(row={"locked": False}), _FakeResult(row={"locked": True})])
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]

        async with repository.writer_lock(timeout_seconds=1.0):
            pass

        attempts = [call for call in session.calls if "pg_try_advisory_xact_lock" in call[0]]
        assert len(attempts) == 2
        assert session.rolled_back is True

    async def test_times_out_as_busy_instead_of_waiting_forever(self) -> None:
        session = _FakeSession([_FakeResult(row={"locked": False})])
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]

        with pytest.raises(PaperLedgerBusyError, match="writer is still running"):
            async with repository.writer_lock(timeout_seconds=0.0):
                pass

        assert session.rolled_back is True

    async def test_wraps_acquisition_failures(self) -> None:
        session = _FakeSession()
        session.execute = AsyncMock(side_effect=RuntimeError("database down"))  # type: ignore[method-assign]
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]

        with pytest.raises(PaperLedgerError, match="writer lock"):
            async with repository.writer_lock(timeout_seconds=0.0):
                pass

    async def test_releases_the_lock_when_the_body_raises(self) -> None:
        session = _FakeSession([_FakeResult(row={"locked": True})])
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="boom"):
            async with repository.writer_lock(timeout_seconds=1.0):
                raise ValueError("boom")

        assert session.rolled_back is True

    async def test_cancelled_writer_still_rolls_back(self) -> None:
        session = _FakeSession([_FakeResult(row={"locked": True})])
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]

        with pytest.raises(asyncio.CancelledError):
            async with repository.writer_lock(timeout_seconds=1.0):
                raise asyncio.CancelledError()

        assert session.rolled_back is True

    async def test_rollback_failure_is_logged_not_raised(self, caplog: pytest.LogCaptureFixture) -> None:
        session = _FakeSession([_FakeResult(row={"locked": True})])
        session.rollback = AsyncMock(side_effect=RuntimeError("rollback failed"))  # type: ignore[method-assign]
        repository = PaperLedgerRepository(_FakeSessionFactory(session))  # type: ignore[arg-type]

        with caplog.at_level("WARNING", logger="ares.paper_trading"):
            async with repository.writer_lock(timeout_seconds=1.0):
                pass

        assert "Could not roll back the paper-ledger writer-lock transaction" in caplog.text


class TestPaperTradingLedgerService:
    def _ledger(self, engine: PaperTradingEngine) -> tuple[PaperTradingLedger, MagicMock]:
        repository = MagicMock(spec=PaperLedgerRepository)
        repository.hydrate = AsyncMock(return_value=True)
        repository.persist = AsyncMock(return_value=True)
        repository.client_order_id_exists = AsyncMock(return_value=False)
        repository.writer_lock = _WriterLockSpy()
        return PaperTradingLedger(engine=engine, repository=repository), repository

    async def test_execute_signal_persists_entry_and_reports_status(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        ledger, repository = self._ledger(engine)

        result = await ledger.execute_signal(
            symbol="BTC-USD",
            side="long",
            quantity=1.0,
            entry_price=50000.0,
            stop_loss=48000.0,
            strategy_name="trend",
            client_order_id="client-1",
        )

        assert result["accepted"] is True
        assert result["ledger_persisted"] is True
        repository.persist.assert_awaited_once()
        persisted = repository.persist.await_args.kwargs
        assert persisted["entry_position_ids"] == [result["position_id"]]
        assert persisted["closed_trades"] == []
        assert persisted["client_order_id"] == "client-1"
        assert len(engine.get_open_positions()) == 1

    async def test_execute_signal_rejects_duplicate_client_order_id_before_mutation(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        ledger, repository = self._ledger(engine)
        repository.client_order_id_exists = AsyncMock(return_value=True)
        before = engine.snapshot()

        with pytest.raises(PaperOrderConflictError, match="already been used"):
            await ledger.execute_signal(
                symbol="BTC-USD",
                side="long",
                quantity=1.0,
                entry_price=50000.0,
                client_order_id="client-1",
            )

        assert engine.snapshot() == before
        repository.persist.assert_not_awaited()

    async def test_execute_signal_rejection_does_not_persist_or_mutate(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        ledger, repository = self._ledger(engine)
        before = engine.snapshot()

        result = await ledger.execute_signal(
            symbol="BTC-USD",
            side="long",
            quantity=0.5,
            entry_price=52000.0,
        )

        assert result["accepted"] is False
        assert engine.snapshot() == before
        repository.persist.assert_not_awaited()

    async def test_execute_signal_rolls_back_engine_when_persist_fails(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        ledger, repository = self._ledger(engine)
        repository.persist = AsyncMock(side_effect=PaperLedgerError("database down"))

        with pytest.raises(PaperLedgerError, match="database down"):
            await ledger.execute_signal(
                symbol="BTC-USD",
                side="long",
                quantity=1.0,
                entry_price=50000.0,
            )

        assert engine.get_open_positions() == []
        assert engine.get_summary().cash == 100000.0

    async def test_execute_signal_rejects_unpersisted_trade_without_seed(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        ledger, repository = self._ledger(engine)
        repository.persist = AsyncMock(return_value=False)

        with pytest.raises(PaperLedgerError, match="not seeded"):
            await ledger.execute_signal(
                symbol="BTC-USD",
                side="long",
                quantity=1.0,
                entry_price=50000.0,
            )

        assert engine.get_open_positions() == []
        assert engine.get_summary().cash == 100000.0

    async def test_process_candle_closes_and_persists(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0, stop_loss=49000.0)
        ledger, repository = self._ledger(engine)

        closed = await ledger.process_candle(
            symbol="BTC-USD",
            high=49500.0,
            low=48000.0,
            close=48500.0,
        )

        assert len(closed) == 1
        assert closed[0].exit_reason == "stop_loss"
        repository.persist.assert_awaited_once()
        assert repository.persist.await_args.kwargs["closed_trades"] == closed

    async def test_process_candle_rolls_back_marks_when_persist_fails(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        before = engine.get_summary()
        ledger, repository = self._ledger(engine)
        repository.persist = AsyncMock(side_effect=PaperLedgerError("database down"))

        with pytest.raises(PaperLedgerError, match="database down"):
            await ledger.process_candle(symbol="BTC-USD", high=51000.0, low=49000.0, close=51000.0)

        after = engine.get_summary()
        assert after.cash == before.cash
        assert engine.get_last_prices()["BTC-USD"] == 50000.0

    async def test_process_candle_rejects_unpersisted_mark_without_seed(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        ledger, repository = self._ledger(engine)
        repository.persist = AsyncMock(return_value=False)

        with pytest.raises(PaperLedgerError, match="not seeded"):
            await ledger.process_candle(symbol="BTC-USD", high=51000.0, low=49000.0, close=51000.0)

        assert engine.get_last_prices()["BTC-USD"] == 50000.0
        assert engine.get_summary().equity == 100000.0

    async def test_execute_signal_holds_the_writer_lock_for_the_whole_cycle(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        ledger, repository = self._ledger(engine)
        spy = repository.writer_lock

        async def hydrate(_engine: PaperTradingEngine) -> bool:
            spy.events.append("hydrate")
            return True

        async def persist(*args: Any, **kwargs: Any) -> bool:
            spy.events.append("persist")
            return True

        repository.hydrate = hydrate
        repository.persist = persist

        await ledger.execute_signal(
            symbol="BTC-USD",
            side="long",
            quantity=1.0,
            entry_price=50000.0,
            client_order_id="client-1",
        )

        assert spy.events == ["lock_enter", "hydrate", "persist", "lock_exit"]
        assert spy.entries == spy.exits == 1

    async def test_execute_signal_releases_the_writer_lock_when_persist_fails(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        ledger, repository = self._ledger(engine)
        repository.persist = AsyncMock(side_effect=PaperLedgerError("database down"))

        with pytest.raises(PaperLedgerError, match="database down"):
            await ledger.execute_signal(
                symbol="BTC-USD",
                side="long",
                quantity=1.0,
                entry_price=50000.0,
            )

        assert repository.writer_lock.entries == repository.writer_lock.exits == 1
        assert engine.get_open_positions() == []

    async def test_execute_signal_rejects_busy_ledger_without_touching_the_cache(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        ledger, repository = self._ledger(engine)

        @asynccontextmanager
        async def busy_lock(*, timeout_seconds: float = 10.0) -> AsyncIterator[None]:
            raise PaperLedgerBusyError("Another paper-ledger writer is still running")
            yield  # pragma: no cover - unreachable, keeps the generator contract

        repository.writer_lock = busy_lock
        before = engine.snapshot()

        with pytest.raises(PaperLedgerBusyError):
            await ledger.execute_signal(
                symbol="BTC-USD",
                side="long",
                quantity=1.0,
                entry_price=50000.0,
            )

        assert engine.snapshot() == before
        repository.hydrate.assert_not_awaited()
        repository.persist.assert_not_awaited()

    async def test_process_candle_uses_the_writer_lock(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0, stop_loss=49000.0)
        ledger, repository = self._ledger(engine)

        await ledger.process_candle(symbol="BTC-USD", high=49500.0, low=48000.0, close=48500.0)

        assert repository.writer_lock.events == ["lock_enter", "lock_exit"]
        assert repository.writer_lock.entries == repository.writer_lock.exits == 1

    async def test_concurrent_writes_do_not_interleave_the_shared_cache(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        repository = MagicMock(spec=PaperLedgerRepository)
        repository.writer_lock = _WriterLockSpy()
        repository.client_order_id_exists = AsyncMock(return_value=False)
        in_flight = 0
        max_in_flight = 0

        async def hydrate(_engine: PaperTradingEngine) -> bool:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0)
            in_flight -= 1
            return True

        async def persist(*args: Any, **kwargs: Any) -> bool:
            await asyncio.sleep(0)
            return True

        repository.hydrate = hydrate
        repository.persist = persist
        ledger = PaperTradingLedger(engine=engine, repository=repository)

        await asyncio.gather(
            ledger.execute_signal(symbol="BTC-USD", side="long", quantity=1.0, entry_price=50000.0),
            ledger.execute_signal(symbol="ETH-USD", side="short", quantity=1.0, entry_price=3000.0),
        )

        assert max_in_flight == 1
        assert len(engine.get_open_positions()) == 2

    async def test_initialize_warns_and_returns_false_without_seed(self) -> None:
        engine = PaperTradingEngine()
        repository = MagicMock(spec=PaperLedgerRepository)
        repository.hydrate = AsyncMock(return_value=False)
        ledger = PaperTradingLedger(engine=engine, repository=repository)

        assert await ledger.initialize() is False
        repository.hydrate.assert_awaited_once()

    async def test_restart_mid_trade_restores_position_and_closes_after_restart(self) -> None:
        """A process restart must not lose an open position or its cost basis."""
        state: dict[str, Any] = {}

        class _MemoryRepository:
            @asynccontextmanager
            async def writer_lock(self, *, timeout_seconds: float = 10.0) -> AsyncIterator[None]:
                yield

            async def hydrate(self, engine: PaperTradingEngine) -> bool:
                if not state:
                    return False
                engine.restore_snapshot(state)
                return True

            async def persist(self, engine: PaperTradingEngine, **kwargs: Any) -> bool:
                state.clear()
                state.update(engine.snapshot())
                return True

        first_engine = PaperTradingEngine(initial_capital=100000.0, commission_pct=0.001, slippage_pct=0.001)
        first = PaperTradingLedger(first_engine, _MemoryRepository())  # type: ignore[arg-type]
        await first.execute_signal(
            symbol="BTC-USD",
            side="long",
            quantity=1.0,
            entry_price=50000.0,
            stop_loss=49000.0,
            strategy_name="trend",
        )
        assert len(first_engine.get_open_positions()) == 1
        assert state["positions"][0].entry_price > 50000.0

        restarted_engine = PaperTradingEngine(initial_capital=1.0)
        second = PaperTradingLedger(restarted_engine, _MemoryRepository())  # type: ignore[arg-type]
        assert await second.initialize() is True
        restored = restarted_engine.get_open_positions()
        assert len(restored) == 1
        assert restored[0].strategy_name == "trend"
        assert restored[0].entry_commission > 0.0

        closed = await second.process_candle(symbol="BTC-USD", high=49500.0, low=48000.0, close=48500.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == "stop_loss"
        assert restarted_engine.get_open_positions() == []
        assert restarted_engine.get_summary().total_trades == 1

    async def test_open_position_symbols_hydrates_under_the_cache_lock(self) -> None:
        engine = PaperTradingEngine(initial_capital=100000.0)
        engine.execute_signal("ETH-USD", "long", 0.1, 3000.0)
        engine.execute_signal("BTC-USD", "long", 0.1, 50000.0)
        ledger, repository = self._ledger(engine)

        assert await ledger.get_open_position_symbols() == ["BTC-USD", "ETH-USD"]
        repository.hydrate.assert_awaited_once()

    async def test_reads_refresh_from_repository(self) -> None:
        engine = PaperTradingEngine()
        ledger, repository = self._ledger(engine)

        summary = await ledger.get_summary()
        positions = await ledger.get_open_positions()
        trades = await ledger.get_closed_trades()

        assert summary.initial_capital == 100000.0
        assert positions == []
        assert trades == []
        assert repository.hydrate.await_count == 3
