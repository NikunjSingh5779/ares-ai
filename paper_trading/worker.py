"""Background worker for Paper Trading Engine.

Polls live market data to evaluate stop-loss and take-profit levels
for open paper-trading positions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.data.ingestor import MarketDataIngestor
from paper_trading.engine import PaperTradingEngine

if TYPE_CHECKING:
    from paper_trading.engine import ClosedTrade


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
    ) -> None:
        self.engine = engine
        self.ingestor = ingestor
        self.session_factory = session_factory
        self.poll_interval = poll_interval_seconds
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
        # 1. Get unique symbols with open positions
        # Access internal list safely (we are the engine's trusted worker)
        open_positions = list(self.engine._positions)  # noqa: SLF001
        symbols = list({pos.symbol for pos in open_positions})

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
            closed = self.engine.check_sl_tp(
                symbol=result.symbol,
                high=float(candle.high),
                low=float(candle.low),
            )
            if closed:
                all_closed_trades.extend(closed)

        # 4. Persist closed trades to database
        if all_closed_trades:
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

                for trade in closed_trades:
                    # Update position
                    await session.execute(
                        text(
                            """
                            UPDATE positions 
                            SET is_open=False, closed_at=:closed_at, current_price=:exit_price,
                                unrealized_pnl=0, realized_pnl=:pnl, market_value=0
                            WHERE portfolio_id=:portfolio_id AND symbol=:symbol AND side=:side AND is_open=True
                            """
                        ),
                        {
                            "closed_at": trade.exit_at,
                            "exit_price": trade.exit_price,
                            "pnl": trade.pnl,
                            "portfolio_id": portfolio_id,
                            "symbol": trade.symbol,
                            "side": trade.side,
                        }
                    )
                    
                    # Update portfolio
                    await session.execute(
                        text(
                            """
                            UPDATE portfolio
                            SET cash_balance = cash_balance + :proceeds,
                                realized_pnl = realized_pnl + :pnl,
                                invested_amount = invested_amount - :entry_value
                            WHERE id=:portfolio_id
                            """
                        ),
                        {
                            "proceeds": trade.quantity * trade.exit_price,
                            "pnl": trade.pnl,
                            "entry_value": trade.quantity * trade.entry_price,
                            "portfolio_id": portfolio_id,
                        }
                    )
                    
                    # Log order
                    await session.execute(
                        text(
                            """
                            INSERT INTO orders (
                                account_id, symbol, side, order_type, status,
                                quantity, price, filled_quantity, avg_fill_price,
                                strategy_name, reason
                            ) VALUES (
                                :account_id, :symbol, :side, 'market', 'filled',
                                :quantity, :price, :quantity, :price,
                                :strategy_name, :reason
                            )
                            """
                        ),
                        {
                            "account_id": account_id,
                            "symbol": trade.symbol,
                            "side": "sell" if trade.side == "long" else "buy",  # Exit order side
                            "quantity": trade.quantity,
                            "price": trade.exit_price,
                            "strategy_name": trade.strategy_name,
                            "reason": trade.exit_reason,
                        }
                    )
                
                await session.commit()
                logger.info("Persisted %d closed trades to DB", len(closed_trades))
        except Exception as e:
            logger.error("Failed to persist closed trades to DB", extra={"error": str(e)}, exc_info=True)
