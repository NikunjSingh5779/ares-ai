"""Application service for the durable paper-trading ledger.

The service coordinates the in-memory calculation cache with the repository:
read the latest database state before an action, mutate the engine, then write
one transaction. If the write fails, the in-memory snapshot is restored so the
cache cannot silently diverge from the ledger.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from paper_trading.engine import ClosedTrade, PaperPosition, PaperTradingEngine, PortfolioSummary
from paper_trading.repository import PaperLedgerError, PaperLedgerRepository, PaperOrderConflictError

logger = logging.getLogger("ares.paper_trading")


class PaperTradingLedger:
    """Single application-facing API for paper execution and marks.

    Two locks protect the shared engine cache:

    * an in-process :class:`asyncio.Lock` around every operation that reads or
      mutates the cache, so concurrent request handlers in one process cannot
      hydrate the cache in the middle of another handler's write;
    * the repository's PostgreSQL advisory lock, held across
      hydrate → mutate → persist, so the API, worker, and runner processes
      cannot overwrite each other's committed state.
    """

    def __init__(
        self,
        engine: PaperTradingEngine,
        repository: PaperLedgerRepository,
        *,
        writer_timeout_seconds: float = 10.0,
    ) -> None:
        self.engine = engine
        self.repository = repository
        self.writer_timeout_seconds = writer_timeout_seconds
        self._cache_lock = asyncio.Lock()

    async def initialize(self) -> bool:
        """Hydrate the engine at process startup."""
        hydrated = await self.refresh()
        if not hydrated:
            logger.warning(
                "Paper ledger account is not seeded; reads serve empty state and writes are rejected. "
                "Run scripts/seed.py to enable paper execution and restart durability."
            )
        return hydrated

    async def _hydrate(self) -> bool:
        """Reload the durable ledger; callers must already hold the cache lock."""
        return await self.repository.hydrate(self.engine)

    async def refresh(self) -> bool:
        """Reload the durable ledger into the cache.

        Returns ``False`` when no paper account/portfolio exists yet. Reads may
        continue against the empty in-memory cache, but writes raise
        :class:`PaperLedgerError` rather than claiming durability.
        """
        async with self._cache_lock:
            return await self._hydrate()

    async def execute_signal(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        strategy_name: str = "",
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute and persist one paper fill.

        ``client_order_id`` is required by the HTTP execution path and is
        checked before mutation. The unique database index is the race-free
        guard. The engine snapshot is rolled back if persistence fails.
        """
        async with self._cache_lock:
            async with self.repository.writer_lock(timeout_seconds=self.writer_timeout_seconds):
                return await self._execute_signal_locked(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    strategy_name=strategy_name,
                    client_order_id=client_order_id,
                )

    async def _execute_signal_locked(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        stop_loss: float | None,
        take_profit: float | None,
        strategy_name: str,
        client_order_id: str | None,
    ) -> dict[str, Any]:
        await self._hydrate()
        if client_order_id and await self.repository.client_order_id_exists(client_order_id):
            raise PaperOrderConflictError("Client order ID has already been used")
        snapshot = self.engine.snapshot()
        closed_before = len(self.engine.get_closed_trades())
        result = self.engine.execute_signal(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_name=strategy_name,
        )
        if not result.get("accepted", False):
            # Rejections must not leave a partial mutation in the cache (for
            # example, a failed reversal after the old position was closed).
            self.engine.restore_snapshot(snapshot)
            return result

        position_id = result.get("position_id")
        new_closed = self.engine.get_closed_trades()[closed_before:]
        try:
            persisted = await self.repository.persist(
                self.engine,
                closed_trades=new_closed,
                entry_position_ids=[position_id] if position_id else [],
                client_order_id=client_order_id,
            )
        except Exception:
            self.engine.restore_snapshot(snapshot)
            raise
        if not persisted:
            # No seeded paper account means there is no durable ledger to
            # write to. Refuse the fill instead of reporting an in-memory
            # trade that a restart would silently lose.
            self.engine.restore_snapshot(snapshot)
            raise PaperLedgerError("Paper ledger account is not seeded; trade was not persisted")
        result["ledger_persisted"] = True
        return result

    async def process_candle(
        self,
        *,
        symbol: str,
        high: float,
        low: float,
        close: float,
    ) -> list[ClosedTrade]:
        """Check exits, mark the position, and persist the resulting state."""
        async with self._cache_lock:
            async with self.repository.writer_lock(timeout_seconds=self.writer_timeout_seconds):
                return await self._process_candle_locked(symbol=symbol, high=high, low=low, close=close)

    async def _process_candle_locked(
        self,
        *,
        symbol: str,
        high: float,
        low: float,
        close: float,
    ) -> list[ClosedTrade]:
        await self._hydrate()
        snapshot = self.engine.snapshot()
        closed = self.engine.check_sl_tp(symbol=symbol, high=high, low=low)
        self.engine.mark_to_market(symbol, close)
        try:
            persisted = await self.repository.persist(self.engine, closed_trades=closed)
        except Exception:
            self.engine.restore_snapshot(snapshot)
            raise
        if not persisted:
            self.engine.restore_snapshot(snapshot)
            raise PaperLedgerError("Paper ledger account is not seeded; candle was not persisted")
        return closed

    async def get_open_position_symbols(self) -> list[str]:
        """Return the symbols with an open position from the latest durable state."""
        async with self._cache_lock:
            await self._hydrate()
            return sorted({position.symbol for position in self.engine.get_open_positions()})

    async def get_summary(self) -> PortfolioSummary:
        """Return a summary built from the latest durable state."""
        async with self._cache_lock:
            await self._hydrate()
            return self.engine.get_summary()

    async def get_open_positions(self) -> list[PaperPosition]:
        """Return open positions from the latest durable state."""
        async with self._cache_lock:
            await self._hydrate()
            return self.engine.get_open_positions()

    async def get_closed_trades(self) -> list[ClosedTrade]:
        """Return closed trades from the latest durable state."""
        async with self._cache_lock:
            await self._hydrate()
            return self.engine.get_closed_trades()
