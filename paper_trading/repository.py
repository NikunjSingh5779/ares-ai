"""Durable persistence for the paper-trading ledger.

The in-memory :class:`~paper_trading.engine.PaperTradingEngine` remains the
calculation cache.  This repository is the only place that reads or writes the
paper account, portfolio, open positions, and closed-trade history, so a
restart can rebuild the cache from PostgreSQL.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from paper_trading.engine import ClosedTrade, PaperPosition, PaperTradingEngine

logger = logging.getLogger("ares.paper_trading")


class PaperLedgerError(RuntimeError):
    """Raised when a paper-ledger read or write cannot be completed."""


class PaperOrderConflictError(PaperLedgerError):
    """Raised when a client order ID was already used for this paper account."""


def _is_client_order_conflict(exc: IntegrityError) -> bool:
    """Identify the client-order unique index across SQLAlchemy drivers."""
    constraint = getattr(getattr(exc, "orig", None), "constraint_name", "") or ""
    return "client_order_id" in str(exc).lower() or constraint == "uq_orders_client_order_id"


class PaperLedgerRepository:
    """Read/write the PostgreSQL paper ledger.

    Every write for one fill, mark, or closure is committed in a single
    transaction.  The API, worker, and runner all use this class through
    :class:`paper_trading.ledger.PaperTradingLedger`.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def client_order_id_exists(self, client_order_id: str) -> bool:
        """Return whether this client order ID is already recorded.

        The unique index is the race-free guard; this read gives the API a
        clean 409 before any engine mutation in the common duplicate case.
        """
        try:
            async with self._session_factory() as session:
                found = (
                    await session.execute(
                        text(
                            """
                            SELECT 1
                            FROM orders o
                            JOIN accounts a ON a.id = o.account_id
                            WHERE a.exchange = 'paper'
                              AND o.client_order_id = :client_order_id
                            LIMIT 1
                            """
                        ),
                        {"client_order_id": client_order_id},
                    )
                ).first()
                return found is not None
        except Exception as exc:  # noqa: BLE001 - preserve DB failure context
            raise PaperLedgerError(f"Could not check client order ID: {exc}") from exc

    async def hydrate(self, engine: PaperTradingEngine) -> bool:
        """Load the paper account into ``engine``.

        Returns ``False`` when the seeded paper account/portfolio does not
        exist.  That is a development state, not a reason to invent a second
        portfolio; callers keep the existing in-memory engine and log the gap.
        """
        try:
            async with self._session_factory() as session:
                portfolio = await self._load_portfolio(session)
                if portfolio is None:
                    return False

                positions, marks = await self._load_positions(session, str(portfolio["portfolio_id"]))
                trades = await self._load_closed_trades(session, str(portfolio["account_id"]))
        except Exception as exc:  # noqa: BLE001 - preserve DB failure context
            raise PaperLedgerError(f"Could not hydrate paper ledger: {exc}") from exc

        initial_capital = float(100000.0 if portfolio["initial_capital"] is None else portfolio["initial_capital"])
        cash_balance = float(initial_capital if portfolio["cash_balance"] is None else portfolio["cash_balance"])
        curve = portfolio["equity_curve"] or []
        if isinstance(curve, str):
            try:
                curve = json.loads(curve)
            except json.JSONDecodeError:
                curve = []
        if not isinstance(curve, list):
            curve = []

        engine.restore_state(
            initial_capital=initial_capital,
            cash=cash_balance,
            positions=positions,
            closed_trades=trades,
            equity_curve=[float(point) for point in curve],
            last_prices=marks,
        )
        return True

    async def _load_portfolio(self, session: AsyncSession) -> dict[str, Any] | None:
        row = (
            (
                await session.execute(
                    text(
                        """
                    SELECT
                        a.id AS account_id,
                        p.id AS portfolio_id,
                        p.initial_capital,
                        p.cash_balance,
                        p.equity_curve
                    FROM accounts a
                    JOIN portfolio p ON p.account_id = a.id
                    WHERE a.exchange = 'paper'
                    ORDER BY p.created_at, p.id
                    LIMIT 1
                    """
                    )
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None

    async def _load_positions(
        self,
        session: AsyncSession,
        portfolio_id: str,
    ) -> tuple[list[PaperPosition], dict[str, float]]:
        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT
                        id, symbol, side, quantity, entry_price, current_price,
                        stop_loss, take_profit, strategy_name, opened_at,
                        entry_commission, margin
                    FROM positions
                    WHERE portfolio_id = :portfolio_id AND is_open = true
                    ORDER BY opened_at, id
                    """
                    ),
                    {"portfolio_id": portfolio_id},
                )
            )
            .mappings()
            .all()
        )

        positions: list[PaperPosition] = []
        marks: dict[str, float] = {}
        for row in rows:
            mark = float(row["current_price"] or row["entry_price"])
            positions.append(
                PaperPosition(
                    id=str(row["id"]),
                    symbol=str(row["symbol"]),
                    side="short" if row["side"] == "short" else "long",
                    quantity=float(row["quantity"]),
                    entry_price=float(row["entry_price"]),
                    entry_at=row["opened_at"] or datetime.now(),
                    stop_loss=float(row["stop_loss"]) if row["stop_loss"] is not None else None,
                    take_profit=float(row["take_profit"]) if row["take_profit"] is not None else None,
                    strategy_name=str(row["strategy_name"] or ""),
                    entry_commission=float(row["entry_commission"] or 0.0),
                    margin=float(row["margin"] or 0.0),
                )
            )
            if mark > 0:
                marks[str(row["symbol"])] = mark
        return positions, marks

    async def _load_closed_trades(self, session: AsyncSession, account_id: str) -> list[ClosedTrade]:
        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT
                        symbol, position_side, side, quantity, entry_price,
                        exit_price, entry_at, exit_at, pnl, pnl_pct,
                        strategy_name, entry_commission, exit_commission,
                        exit_reason
                    FROM trade_history
                    WHERE account_id = :account_id AND is_closed = true
                    ORDER BY exit_at NULLS LAST, created_at, id
                    """
                    ),
                    {"account_id": account_id},
                )
            )
            .mappings()
            .all()
        )

        trades: list[ClosedTrade] = []
        for row in rows:
            stored_side = str(row["position_side"] or "")
            if stored_side not in ("long", "short"):
                stored_side = "long" if row["side"] == "buy" else "short"
            trades.append(
                ClosedTrade(
                    symbol=str(row["symbol"]),
                    side="short" if stored_side == "short" else "long",
                    quantity=float(row["quantity"]),
                    entry_price=float(row["entry_price"]),
                    exit_price=float(row["exit_price"] or row["entry_price"]),
                    entry_at=row["entry_at"] or datetime.now(),
                    exit_at=row["exit_at"] or datetime.now(),
                    pnl=float(row["pnl"] or 0.0),
                    pnl_pct=float(row["pnl_pct"] or 0.0),
                    exit_reason=str(row["exit_reason"] or "signal"),
                    strategy_name=str(row["strategy_name"] or ""),
                    entry_commission=float(row["entry_commission"] or 0.0),
                    exit_commission=float(row["exit_commission"] or 0.0),
                )
            )
        return trades

    async def persist(
        self,
        engine: PaperTradingEngine,
        *,
        closed_trades: Sequence[ClosedTrade] = (),
        entry_position_ids: Sequence[str] = (),
        client_order_id: str | None = None,
    ) -> bool:
        """Persist the engine snapshot and any newly closed trades atomically.

        ``entry_position_ids`` identifies positions that need an entry order
        row.  Without it, marking an existing position does not duplicate order
        history. ``client_order_id`` is attached to the new entry order for
        idempotency; exit orders keep their own generated identity.  Returns
        ``False`` when the seeded paper account is missing.
        """
        try:
            async with self._session_factory() as session:
                portfolio = await self._load_portfolio(session)
                if portfolio is None:
                    logger.warning("Paper trading account not found; ledger write skipped")
                    return False

                account_id = str(portfolio["account_id"])
                portfolio_id = str(portfolio["portfolio_id"])
                entry_ids = set(entry_position_ids)

                for position in engine.get_open_positions():
                    await self._upsert_position(session, portfolio_id, position, engine)
                    if position.id in entry_ids:
                        await self._insert_order(
                            session,
                            account_id=account_id,
                            symbol=position.symbol,
                            side="buy" if position.side == "long" else "sell",
                            quantity=position.quantity,
                            price=position.entry_price,
                            position_id=position.id,
                            client_order_id=client_order_id,
                            rationale={
                                "strategy_name": position.strategy_name,
                                "event": "entry",
                                "side": position.side,
                            },
                        )

                for trade in closed_trades:
                    await self._close_position(session, portfolio_id, trade)
                    await self._insert_trade_history(session, account_id, trade)
                    await self._insert_order(
                        session,
                        account_id=account_id,
                        symbol=trade.symbol,
                        side="sell" if trade.side == "long" else "buy",
                        quantity=trade.quantity,
                        price=trade.exit_price,
                        position_id=trade.position_id or None,
                        client_order_id=None,
                        rationale={
                            "strategy_name": trade.strategy_name,
                            "event": "exit",
                            "exit_reason": trade.exit_reason,
                            "side": trade.side,
                        },
                    )

                await self._update_portfolio(session, portfolio_id, engine)
                await session.commit()
                return True
        except IntegrityError as exc:
            if _is_client_order_conflict(exc):
                raise PaperOrderConflictError("Client order ID has already been used") from exc
            raise PaperLedgerError(f"Could not persist paper ledger: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - wrap repository failures
            raise PaperLedgerError(f"Could not persist paper ledger: {exc}") from exc

    async def _upsert_position(
        self,
        session: AsyncSession,
        portfolio_id: str,
        position: PaperPosition,
        engine: PaperTradingEngine,
    ) -> None:
        mark = engine.get_last_prices().get(position.symbol, position.entry_price)
        unrealized = (
            (mark - position.entry_price) * position.quantity
            if position.side == "long"
            else (position.entry_price - mark) * position.quantity
        )
        entry_value = position.quantity * position.entry_price
        unrealized_pct = (unrealized / entry_value * 100.0) if entry_value > 0 else 0.0
        await session.execute(
            text(
                """
                INSERT INTO positions (
                    id, portfolio_id, symbol, asset_type, side, quantity,
                    entry_price, current_price, market_value, unrealized_pnl,
                    unrealized_pnl_pct, stop_loss, take_profit, strategy_name,
                    opened_at, is_open, entry_commission, margin
                ) VALUES (
                    :id, :portfolio_id, :symbol, 'crypto', :side, :quantity,
                    :entry_price, :current_price, :market_value, :unrealized_pnl,
                    :unrealized_pnl_pct, :stop_loss, :take_profit, :strategy_name,
                    :opened_at, true, :entry_commission, :margin
                )
                ON CONFLICT (id) DO UPDATE SET
                    symbol = EXCLUDED.symbol,
                    side = EXCLUDED.side,
                    quantity = EXCLUDED.quantity,
                    entry_price = EXCLUDED.entry_price,
                    current_price = EXCLUDED.current_price,
                    market_value = EXCLUDED.market_value,
                    unrealized_pnl = EXCLUDED.unrealized_pnl,
                    unrealized_pnl_pct = EXCLUDED.unrealized_pnl_pct,
                    stop_loss = EXCLUDED.stop_loss,
                    take_profit = EXCLUDED.take_profit,
                    strategy_name = EXCLUDED.strategy_name,
                    is_open = true,
                    entry_commission = EXCLUDED.entry_commission,
                    margin = EXCLUDED.margin,
                    updated_at = NOW()
                """
            ),
            {
                "id": position.id,
                "portfolio_id": portfolio_id,
                "symbol": position.symbol,
                "side": position.side,
                "quantity": position.quantity,
                "entry_price": position.entry_price,
                "current_price": mark,
                "market_value": position.quantity * mark,
                "unrealized_pnl": unrealized,
                "unrealized_pnl_pct": unrealized_pct,
                "stop_loss": position.stop_loss,
                "take_profit": position.take_profit,
                "strategy_name": position.strategy_name,
                "opened_at": position.entry_at,
                "entry_commission": position.entry_commission,
                "margin": position.margin,
            },
        )

    async def _close_position(
        self,
        session: AsyncSession,
        portfolio_id: str,
        trade: ClosedTrade,
    ) -> None:
        if trade.position_id:
            await session.execute(
                text(
                    """
                    UPDATE positions
                    SET is_open = false, closed_at = :closed_at,
                        current_price = :exit_price, market_value = 0,
                        unrealized_pnl = 0, unrealized_pnl_pct = 0,
                        updated_at = NOW()
                    WHERE id = :position_id
                    """
                ),
                {
                    "closed_at": trade.exit_at,
                    "exit_price": trade.exit_price,
                    "position_id": trade.position_id,
                },
            )
            return

        # Older rows/reversal records may not carry a position id. Fall back to
        # the engine invariant: one open position per symbol, with a side now
        # stored explicitly so a short is not mistaken for a long.
        await session.execute(
            text(
                """
                UPDATE positions
                SET is_open = false, closed_at = :closed_at,
                    current_price = :exit_price, market_value = 0,
                    unrealized_pnl = 0, unrealized_pnl_pct = 0,
                    updated_at = NOW()
                WHERE portfolio_id = :portfolio_id AND symbol = :symbol
                  AND side = :side AND is_open = true
                """
            ),
            {
                "closed_at": trade.exit_at,
                "exit_price": trade.exit_price,
                "portfolio_id": portfolio_id,
                "symbol": trade.symbol,
                "side": trade.side,
            },
        )

    async def _insert_trade_history(
        self,
        session: AsyncSession,
        account_id: str,
        trade: ClosedTrade,
    ) -> None:
        await session.execute(
            text(
                """
                INSERT INTO trade_history (
                    account_id, symbol, position_side, side, quantity,
                    entry_price, exit_price, entry_at, exit_at, pnl, pnl_pct,
                    is_closed, strategy_name, entry_commission, exit_commission,
                    exit_reason, agent_rationale
                ) VALUES (
                    :account_id, :symbol, :position_side, :side, :quantity,
                    :entry_price, :exit_price, :entry_at, :exit_at, :pnl, :pnl_pct,
                    true, :strategy_name, :entry_commission, :exit_commission,
                    :exit_reason, CAST(:rationale AS JSONB)
                )
                """
            ),
            {
                "account_id": account_id,
                "symbol": trade.symbol,
                "position_side": trade.side,
                "side": "buy" if trade.side == "long" else "sell",
                "quantity": trade.quantity,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "entry_at": trade.entry_at,
                "exit_at": trade.exit_at,
                "pnl": trade.pnl,
                "pnl_pct": trade.pnl_pct,
                "strategy_name": trade.strategy_name,
                "entry_commission": trade.entry_commission,
                "exit_commission": trade.exit_commission,
                "exit_reason": trade.exit_reason,
                "rationale": json.dumps(
                    {
                        "strategy_name": trade.strategy_name,
                        "exit_reason": trade.exit_reason,
                        "side": trade.side,
                    }
                ),
            },
        )

    async def _insert_order(
        self,
        session: AsyncSession,
        *,
        account_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        position_id: str | None,
        client_order_id: str | None,
        rationale: dict[str, Any],
    ) -> None:
        await session.execute(
            text(
                """
                INSERT INTO orders (
                    account_id, position_id, symbol, side, order_type, status,
                    quantity, price, filled_quantity, avg_fill_price,
                    client_order_id, agent_rationale
                ) VALUES (
                    :account_id, :position_id, :symbol, :side, 'market', 'filled',
                    :quantity, :price, :quantity, :price,
                    :client_order_id, CAST(:rationale AS JSONB)
                )
                """
            ),
            {
                "account_id": account_id,
                "position_id": position_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "client_order_id": client_order_id,
                "rationale": json.dumps(rationale),
            },
        )

    async def _update_portfolio(
        self,
        session: AsyncSession,
        portfolio_id: str,
        engine: PaperTradingEngine,
    ) -> None:
        summary = engine.get_summary()
        closed = engine.get_closed_trades()
        realized_pnl = sum(trade.pnl for trade in closed)
        invested_amount = sum(position.quantity * position.entry_price for position in engine.get_open_positions())
        await session.execute(
            text(
                """
                UPDATE portfolio
                SET initial_capital = :initial_capital,
                    total_value = :total_value,
                    cash_balance = :cash,
                    invested_amount = :invested_amount,
                    unrealized_pnl = :unrealized_pnl,
                    realized_pnl = :realized_pnl,
                    roi_pct = :roi_pct,
                    max_drawdown_pct = :max_drawdown_pct,
                    margin_used = :margin_used,
                    equity_curve = CAST(:equity_curve AS JSONB),
                    updated_at = NOW()
                WHERE id = :portfolio_id
                """
            ),
            {
                "initial_capital": summary.initial_capital,
                "total_value": summary.equity,
                "cash": summary.cash,
                "invested_amount": invested_amount,
                "unrealized_pnl": summary.total_pnl - realized_pnl,
                "realized_pnl": realized_pnl,
                "roi_pct": summary.total_return_pct,
                "max_drawdown_pct": summary.max_drawdown_pct,
                "margin_used": summary.margin_used,
                "equity_curve": json.dumps(engine.get_equity_curve()),
                "portfolio_id": portfolio_id,
            },
        )
