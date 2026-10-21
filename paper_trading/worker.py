"""Background worker for Paper Trading Engine.

Polls live market data to evaluate stop-loss and take-profit levels
for open paper-trading positions.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.data.ingestor import MarketDataIngestor
from paper_trading.engine import PaperTradingEngine

if TYPE_CHECKING:
    from paper_trading.engine import ClosedTrade
    from paper_trading.ledger import PaperTradingLedger


logger = logging.getLogger("ares.paper_trading")


class PaperTradingWorker:
    """Background worker that continuously evaluates paper trading positions.

    Fetches the latest candle for all open symbols and checks SL/TP.
    If positions are closed, updates the database automatically.
    """

    def __init__(
        self,
        engine: PaperTradingEngine,
        ingestor: MarketDataIngestor,
        session_factory: async_sessionmaker[AsyncSession],
        poll_interval_seconds: int = 60,
        ledger: PaperTradingLedger | None = None,
    ) -> None:
        self.engine = engine
        self.ingestor = ingestor
        self.session_factory = session_factory
        self.poll_interval = poll_interval_seconds
        self.ledger = ledger
        self._running = False
        self._task: asyncio.Task[Any] | None = None

    def start(self) -> None:
        """Start the background polling loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("PaperTradingWorker started (interval=%ds)", self.poll_interval)

    async def stop(self) -> None:
        """Stop the background polling loop."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("PaperTradingWorker stopped")

    async def _loop(self) -> None:
        """Main background loop."""
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in PaperTradingWorker loop", extra={"error": str(e)}, exc_info=True)

            # Sleep for the polling interval
            await asyncio.sleep(self.poll_interval)

    async def _tick(self) -> None:
        """Single iteration of the polling loop."""
        # 1. Get unique symbols with open positions. When a ledger is wired,
        # hydrate under its cache lock so a concurrent fill cannot be observed
        # halfway through.
        if self.ledger is not None:
            symbols = await self.ledger.get_open_position_symbols()
        else:
            symbols = sorted({pos.symbol for pos in self.engine.get_open_positions()})

        if not symbols:
            return

        # 2. Fetch latest 1m candles for these symbols
        results = await self.ingestor.ingest_batch(
            symbols=symbols,
            source="yahoo",  # Can be configured or derived from positions
            interval="1m",
            limit=1,
        )

        all_closed_trades: list[ClosedTrade] = []

        # 3. Check SL/TP
        for result in results:
            if not result.candles:
                continue
            candle = result.candles[-1]
            # Check exits first; a stop fill should not be preceded by a mark
            # at a worse candle close. Then mark any position that remains open
            # so intra-trade drawdown reflects every bar.
            if self.ledger is not None:
                closed = await self.ledger.process_candle(
                    symbol=result.symbol,
                    high=float(candle.high),
                    low=float(candle.low),
                    close=float(candle.close),
                )
            else:
                closed = self.engine.check_sl_tp(
                    symbol=result.symbol,
                    high=float(candle.high),
                    low=float(candle.low),
                )
                self.engine.mark_to_market(result.symbol, float(candle.close))
            if closed:
                all_closed_trades.extend(closed)

        # 4. Persist closed trades to database. The ledger path already wrote
        # the closure and marks atomically; this fallback is for direct engine
        # callers and tests that do not use the repository.
        if all_closed_trades and self.ledger is None:
            await self._persist_closed_trades(all_closed_trades)

    async def _persist_closed_trades(self, closed_trades: list[ClosedTrade]) -> None:
        """Update database for positions that were closed by SL/TP."""
        try:
            async with self.session_factory() as session:
                # Get the default paper trading account
                account_id = (
                    await session.execute(text("SELECT id FROM accounts WHERE exchange='paper' LIMIT 1"))
                ).scalar()

                if not account_id:
                    logger.warning("Paper trading account not found in DB. Cannot persist closed trades.")
                    return

                portfolio_id = (
                    await session.execute(
                        text("SELECT id FROM portfolio WHERE account_id=:account_id LIMIT 1"),
                        {"account_id": account_id},
                    )
                ).scalar()

                if not portfolio_id:
                    return

                summary = self.engine.get_summary()
                realized_pnl = sum(t.pnl for t in self.engine.get_closed_trades())
                invested_amount = sum(pos.quantity * pos.entry_price for pos in self.engine.get_open_positions())

                for trade in closed_trades:
                    # One open position per symbol is enforced by the paper
                    # engine; side makes the closure unambiguous for shorts.
                    await session.execute(
                        text(
                            """
                            UPDATE positions
                            SET is_open=False, closed_at=:closed_at, current_price=:exit_price,
                                unrealized_pnl=0, unrealized_pnl_pct=0, market_value=0
                            WHERE portfolio_id=:portfolio_id AND symbol=:symbol
                              AND side=:side AND is_open=True
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

                    # Fallback path only (no repository wired): mirror the
                    # direct-engine state into the portfolio row so tests and
                    # legacy callers still see a consistent snapshot.
                    await session.execute(
                        text(
                            """
                            UPDATE portfolio
                            SET initial_capital=:initial_capital,
                                total_value=:total_value,
                                cash_balance=:cash,
                                invested_amount=:invested_amount,
                                unrealized_pnl=:unrealized_pnl,
                                realized_pnl=:realized_pnl,
                                margin_used=:margin_used,
                                roi_pct=:roi_pct,
                                max_drawdown_pct=:max_drawdown_pct,
                                equity_curve=CAST(:equity_curve AS JSONB)
                            WHERE id=:portfolio_id
                            """
                        ),
                        {
                            "initial_capital": summary.initial_capital,
                            "total_value": summary.equity,
                            "cash": summary.cash,
                            "invested_amount": invested_amount,
                            "unrealized_pnl": summary.total_pnl - realized_pnl,
                            "realized_pnl": realized_pnl,
                            "margin_used": summary.margin_used,
                            "roi_pct": summary.total_return_pct,
                            "max_drawdown_pct": summary.max_drawdown_pct,
                            "equity_curve": json.dumps(self.engine.get_equity_curve()),
                            "portfolio_id": portfolio_id,
                        },
                    )

                    # Persist the closed trade so the promotion gate can count
                    # it. trade_history uses buy/sell, not long/short.
                    await session.execute(
                        text(
                            """
                            INSERT INTO trade_history (
                                account_id, symbol, position_side, side, quantity,
                                entry_price, exit_price, entry_at, exit_at, pnl,
                                pnl_pct, is_closed, strategy_name, entry_commission,
                                exit_commission, exit_reason
                            ) VALUES (
                                :account_id, :symbol, :position_side, :side, :quantity,
                                :entry_price, :exit_price, :entry_at, :exit_at, :pnl,
                                :pnl_pct, true, :strategy_name, :entry_commission,
                                :exit_commission, :exit_reason
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
                        },
                    )

                    # Log order
                    await session.execute(
                        text(
                            """
                            INSERT INTO orders (
                                account_id, symbol, side, order_type, status,
                                quantity, price, filled_quantity, avg_fill_price,
                                agent_rationale
                            ) VALUES (
                                :account_id, :symbol, :side, 'market', 'filled',
                                :quantity, :price, :quantity, :price,
                                CAST(:rationale AS JSONB)
                            )
                            """
                        ),
                        {
                            "account_id": account_id,
                            "symbol": trade.symbol,
                            "side": "sell" if trade.side == "long" else "buy",  # Exit order side
                            "quantity": trade.quantity,
                            "price": trade.exit_price,
                            "rationale": json.dumps(
                                {
                                    "strategy_name": trade.strategy_name,
                                    "exit_reason": trade.exit_reason,
                                }
                            ),
                        },
                    )

                await session.commit()
                logger.info("Persisted %d closed trades to DB", len(closed_trades))
        except Exception as e:
            logger.error("Failed to persist closed trades to DB", extra={"error": str(e)}, exc_info=True)
