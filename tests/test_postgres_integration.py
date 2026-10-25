"""Real-PostgreSQL integration tests for the durable paper ledger.

These tests are opt-in. They run only when ``ARES_TEST_POSTGRES_URL`` points at
a disposable PostgreSQL database whose name contains ``test``; CI sets it in
the dedicated ``postgres-integration`` job. They cover the Phase 1 exit path
(hydrate -> fill -> restart -> close) and the cross-process guarantees that
unit tests can only fake:

* the partial unique index on ``orders.client_order_id``;
* the transaction-scoped writer advisory lock across competing writers;
* a writer that cannot get the lock failing closed without mutating state.

The setup truncates ``users``/``accounts`` and the paper tables. The database
name guard below is a safety gate: never point this at a real ledger.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from paper_trading.engine import PaperTradingEngine
from paper_trading.ledger import PaperTradingLedger
from paper_trading.repository import (
    PaperLedgerBusyError,
    PaperLedgerRepository,
    PaperOrderConflictError,
)

_TEST_DATABASE_URL = os.getenv("ARES_TEST_POSTGRES_URL")
if not _TEST_DATABASE_URL:
    if os.getenv("ARES_REQUIRE_POSTGRES_INTEGRATION"):
        raise RuntimeError(
            "ARES_REQUIRE_POSTGRES_INTEGRATION is set but ARES_TEST_POSTGRES_URL is "
            "missing; the PostgreSQL integration job must not skip silently"
        )
    pytest.skip(
        "Set ARES_TEST_POSTGRES_URL to a disposable PostgreSQL database to run these tests",
        allow_module_level=True,
    )

assert _TEST_DATABASE_URL is not None  # narrowed for type checkers after pytest.skip
DATABASE_URL: str = _TEST_DATABASE_URL
_DATABASE_NAME = make_url(DATABASE_URL).database or ""
if "test" not in _DATABASE_NAME.lower():
    raise RuntimeError(
        f"ARES_TEST_POSTGRES_URL database {_DATABASE_NAME!r} is not a test database; refusing to truncate it"
    )

_INITIAL_CAPITAL = 100_000.0
_LEDGER_TABLES = "trade_history, orders, positions, portfolio, accounts, users"


def _new_engine() -> AsyncEngine:
    """Create a fresh engine so each call behaves like a separate process."""
    return create_async_engine(DATABASE_URL, poolclass=NullPool)


async def _truncate(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {_LEDGER_TABLES} RESTART IDENTITY CASCADE"))


async def _seed_paper_account(engine: AsyncEngine) -> None:
    """Create the one paper account/portfolio the ledger requires."""
    async with engine.begin() as connection:
        user_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO users (email, password_hash, display_name)
                    VALUES ('integration@ares.test', 'not-a-real-hash', 'Integration')
                    RETURNING id
                    """
                )
            )
        ).scalar_one()
        account_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO accounts (user_id, exchange, account_name, is_active)
                    VALUES (:user_id, 'paper', 'Paper Integration', true)
                    RETURNING id
                    """
                ),
                {"user_id": user_id},
            )
        ).scalar_one()
        await connection.execute(
            text(
                """
                INSERT INTO portfolio (account_id, initial_capital, total_value, cash_balance)
                VALUES (:account_id, :initial_capital, :initial_capital, :initial_capital)
                """
            ),
            {"account_id": account_id, "initial_capital": _INITIAL_CAPITAL},
        )


async def _rows(sql: str, params: dict[str, Any] | None = None) -> list[tuple[Any, ...]]:
    """Read committed state through a separate engine, as an observer process would."""
    engine = _new_engine()
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql), params or {})
            return [tuple(row) for row in result.all()]
    finally:
        await engine.dispose()


@pytest.fixture
async def paper_db() -> AsyncIterator[None]:
    engine = _new_engine()
    try:
        await _truncate(engine)
        await _seed_paper_account(engine)
        yield
    finally:
        await _truncate(engine)
        await engine.dispose()


@asynccontextmanager
async def _paper_process(*, writer_timeout_seconds: float = 5.0) -> AsyncIterator[PaperTradingLedger]:
    """Build an API/worker-style ledger with its own engine and connection pool."""
    engine = _new_engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ledger = PaperTradingLedger(
        PaperTradingEngine(initial_capital=_INITIAL_CAPITAL),
        PaperLedgerRepository(session_factory),
        writer_timeout_seconds=writer_timeout_seconds,
    )
    try:
        yield ledger
    finally:
        await engine.dispose()


async def test_fill_survives_restart_and_close_persists(paper_db: None) -> None:
    async with _paper_process() as first:
        assert await first.initialize() is True
        result = await first.execute_signal(
            symbol="BTC/USDT",
            side="long",
            quantity=1.0,
            entry_price=50_000.0,
            stop_loss=45_000.0,
            take_profit=55_000.0,
            strategy_name="integration",
            client_order_id="itest-fill-1",
        )
        assert result["accepted"] is True
        assert result["ledger_persisted"] is True

    # A new process must rebuild position and cash from PostgreSQL alone.
    async with _paper_process() as second:
        assert await second.initialize() is True
        positions = second.engine.get_open_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "BTC/USDT"
        assert positions[0].side == "long"
        assert positions[0].quantity == pytest.approx(1.0)
        assert positions[0].entry_price == pytest.approx(50_000.0)
        assert second.engine.get_summary().cash == pytest.approx(50_000.0)

        closed = await second.process_candle(symbol="BTC/USDT", high=56_000.0, low=49_000.0, close=55_500.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == "take_profit"
        assert closed[0].exit_price == pytest.approx(55_000.0)

    # Restart again: the closure and realized PnL are durable.
    async with _paper_process() as third:
        assert await third.initialize() is True
        assert third.engine.get_open_positions() == []
        trades = third.engine.get_closed_trades()
        assert len(trades) == 1
        assert trades[0].pnl == pytest.approx(5_000.0)
        assert third.engine.get_summary().cash == pytest.approx(105_000.0)

    position_rows = await _rows("SELECT is_open, closed_at FROM positions WHERE symbol = 'BTC/USDT'")
    assert len(position_rows) == 1
    assert position_rows[0][0] is False
    assert position_rows[0][1] is not None

    trade_rows = await _rows("SELECT pnl, exit_reason FROM trade_history")
    assert len(trade_rows) == 1
    assert float(trade_rows[0][0]) == pytest.approx(5_000.0)
    assert trade_rows[0][1] == "take_profit"

    order_rows = await _rows("SELECT side, client_order_id FROM orders ORDER BY client_order_id NULLS LAST")
    assert len(order_rows) == 2
    assert order_rows[0][0] == "buy"
    assert order_rows[0][1] == "itest-fill-1"
    assert order_rows[1][0] == "sell"
    assert order_rows[1][1] is None

    portfolio_rows = await _rows("SELECT cash_balance, realized_pnl FROM portfolio")
    assert len(portfolio_rows) == 1
    assert float(portfolio_rows[0][0]) == pytest.approx(105_000.0)
    assert float(portfolio_rows[0][1]) == pytest.approx(5_000.0)


async def test_duplicate_client_order_id_is_rejected_after_restart(paper_db: None) -> None:
    async with _paper_process() as first:
        assert await first.initialize() is True
        result = await first.execute_signal(
            symbol="ETH/USDT",
            side="long",
            quantity=1.0,
            entry_price=2_000.0,
            client_order_id="itest-dup-1",
        )
        assert result["accepted"] is True

    async with _paper_process() as second:
        assert await second.initialize() is True
        with pytest.raises(PaperOrderConflictError):
            await second.execute_signal(
                symbol="ETH/USDT",
                side="long",
                quantity=1.0,
                entry_price=2_000.0,
                client_order_id="itest-dup-1",
            )
        # The conflict is detected before any cache mutation.
        assert len(second.engine.get_open_positions()) == 1
        assert second.engine.get_summary().cash == pytest.approx(98_000.0)

    order_rows = await _rows("SELECT count(*) FROM orders WHERE client_order_id = 'itest-dup-1'")
    assert int(order_rows[0][0]) == 1
    position_rows = await _rows("SELECT count(*) FROM positions WHERE is_open = true")
    assert int(position_rows[0][0]) == 1


async def test_concurrent_fills_keep_both_positions_and_cash(paper_db: None) -> None:
    async with _paper_process() as first, _paper_process() as second:
        results = await asyncio.gather(
            first.execute_signal(
                symbol="BTC/USDT",
                side="long",
                quantity=1.0,
                entry_price=50_000.0,
                client_order_id="itest-concurrent-long",
            ),
            second.execute_signal(
                symbol="ETH/USDT",
                side="short",
                quantity=1.0,
                entry_price=2_000.0,
                client_order_id="itest-concurrent-short",
            ),
            return_exceptions=True,
        )

    assert all(isinstance(result, dict) and result["accepted"] is True for result in results), results
    position_rows = await _rows("SELECT symbol, side FROM positions WHERE is_open = true ORDER BY symbol")
    assert position_rows == [("BTC/USDT", "long"), ("ETH/USDT", "short")]
    order_rows = await _rows("SELECT count(*) FROM orders")
    assert int(order_rows[0][0]) == 2
    portfolio_rows = await _rows("SELECT cash_balance FROM portfolio")
    # 100,000 - 50,000 (long) + 2,000 (short proceeds) = 52,000.
    assert float(portfolio_rows[0][0]) == pytest.approx(52_000.0)


async def test_concurrent_duplicate_client_order_id_accepts_exactly_one(paper_db: None) -> None:
    async with _paper_process() as first, _paper_process() as second:
        results = await asyncio.gather(
            first.execute_signal(
                symbol="SOL/USDT",
                side="long",
                quantity=1.0,
                entry_price=100.0,
                client_order_id="itest-race-1",
            ),
            second.execute_signal(
                symbol="SOL/USDT",
                side="long",
                quantity=1.0,
                entry_price=100.0,
                client_order_id="itest-race-1",
            ),
            return_exceptions=True,
        )

    accepted = [result for result in results if isinstance(result, dict) and result["accepted"] is True]
    conflicts = [result for result in results if isinstance(result, PaperOrderConflictError)]
    assert len(accepted) == 1, results
    assert len(conflicts) == 1, results

    order_rows = await _rows("SELECT count(*) FROM orders WHERE client_order_id = 'itest-race-1'")
    assert int(order_rows[0][0]) == 1
    position_rows = await _rows("SELECT count(*) FROM positions WHERE is_open = true")
    assert int(position_rows[0][0]) == 1


async def test_busy_writer_fails_closed_then_retry_succeeds(paper_db: None) -> None:
    async with _paper_process() as holder, _paper_process(writer_timeout_seconds=0.2) as blocked:
        assert await holder.initialize() is True
        async with holder.repository.writer_lock(timeout_seconds=2.0):
            with pytest.raises(PaperLedgerBusyError):
                await blocked.execute_signal(
                    symbol="BTC/USDT",
                    side="long",
                    quantity=1.0,
                    entry_price=50_000.0,
                    client_order_id="itest-busy-1",
                )

        # The failed attempt must not have written or cached anything.
        assert await blocked.repository.client_order_id_exists("itest-busy-1") is False
        retry = await blocked.execute_signal(
            symbol="BTC/USDT",
            side="long",
            quantity=1.0,
            entry_price=50_000.0,
            client_order_id="itest-busy-1",
        )
        assert retry["accepted"] is True

    order_rows = await _rows("SELECT count(*) FROM orders WHERE client_order_id = 'itest-busy-1'")
    assert int(order_rows[0][0]) == 1
