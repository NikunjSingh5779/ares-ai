"""Tests for the durable paper-trading ledger and its repository.

These tests use a small fake async session instead of PostgreSQL so they stay
deterministic and run in CI. The SQL is inspected at the parameter boundary;
the real database round-trip is verified manually against PostgreSQL 16.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from paper_trading.engine import ClosedTrade, PaperTradingEngine
from paper_trading.ledger import PaperTradingLedger
from paper_trading.repository import PaperLedgerError, PaperLedgerRepository


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


class TestPaperTradingLedgerService:
    def _ledger(self, engine: PaperTradingEngine) -> tuple[PaperTradingLedger, MagicMock]:
        repository = MagicMock(spec=PaperLedgerRepository)
        repository.hydrate = AsyncMock(return_value=True)
        repository.persist = AsyncMock(return_value=True)
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
        )

        assert result["accepted"] is True
        assert result["ledger_persisted"] is True
        repository.persist.assert_awaited_once()
        persisted = repository.persist.await_args.kwargs
        assert persisted["entry_position_ids"] == [result["position_id"]]
        assert persisted["closed_trades"] == []
        assert len(engine.get_open_positions()) == 1

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
