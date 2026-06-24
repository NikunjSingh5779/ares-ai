"""Database repository for market data operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.models import OHLCVData, MarketDataSummary


class MarketDataRepository:
    """Repository for market_data table operations.

    Handles insert, bulk insert, and query operations against the
    market_data table defined in database/schema.sql.
    """

    INSERT_SQL = text("""
        INSERT INTO market_data (symbol, source, interval, timestamp, open, high, low, close, volume, vwap, trades_count)
        VALUES (:symbol, :source, :interval, :timestamp, :open, :high, :low, :close, :volume, :vwap, :trades_count)
        ON CONFLICT (symbol, source, interval, timestamp)
        DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            vwap = EXCLUDED.vwap,
            trades_count = EXCLUDED.trades_count
    """)

    QUERY_SQL = text("""
        SELECT symbol, source, interval, timestamp, open, high, low, close, volume, vwap, trades_count
        FROM market_data
        WHERE symbol = :symbol
          AND interval = :interval
          AND (:source IS NULL OR source = :source)
          AND (:start_date IS NULL OR timestamp >= :start_date)
          AND (:end_date IS NULL OR timestamp <= :end_date)
        ORDER BY timestamp {order}
        LIMIT :limit
        OFFSET :offset
    """)

    SUMMARY_SQL = text("""
        SELECT
            symbol,
            source,
            interval,
            COUNT(*) AS count,
            MIN(timestamp) AS first_timestamp,
            MAX(timestamp) AS last_timestamp,
            MAX(high) AS high,
            MIN(low) AS low,
            AVG(close) AS avg_close,
            SUM(volume) AS total_volume
        FROM market_data
        WHERE symbol = :symbol
          AND interval = :interval
        GROUP BY symbol, source, interval
    """)

    CHECK_EXISTS_SQL = text("""
        SELECT COUNT(*) FROM market_data
        WHERE symbol = :symbol AND source = :source AND interval = :interval
        LIMIT 1
    """)

    def __init__(self, session_factory: type[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory

    async def insert_ohlcv(self, candles: list[OHLCVData], session: AsyncSession | None = None) -> int:
        """Insert OHLCV data into market_data table. Returns count inserted.

        Uses INSERT ... ON CONFLICT DO UPDATE to handle duplicates.
        """
        if not candles:
            return 0

        if session is not None:
            return await self._do_insert(session, candles)

        if self._session_factory is None:
            raise RuntimeError("No session factory configured for MarketDataRepository")

        async with self._session_factory() as session:
            try:
                count = await self._do_insert(session, candles)
                await session.commit()
                return count
            except Exception:
                await session.rollback()
                raise

    async def _do_insert(self, session: AsyncSession, candles: list[OHLCVData]) -> int:
        """Execute the actual insert."""
        params = [c.model_dump_for_db() for c in candles]
        for p in params:
            # Ensure valid interval (schema constraint)
            assert p["interval"] in ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"), (
                f"Invalid interval: {p['interval']}"
            )
            # Ensure valid source
            assert p["source"] in ("yahoo", "coingecko", "binance"), (
                f"Invalid source: {p['source']}"
            )

        await session.execute(self.INSERT_SQL, params)
        return len(candles)

    async def query_ohlcv(
        self,
        symbol: str,
        interval: str = "1d",
        source: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 500,
        offset: int = 0,
        order: str = "desc",
        session: AsyncSession | None = None,
    ) -> list[OHLCVData]:
        """Query market data with filters.

        Returns OHLCVData objects ordered by timestamp.
        """
        if session is None:
            if self._session_factory is None:
                raise RuntimeError("No session factory configured")
            async with self._session_factory() as s:
                return await self._do_query(s, symbol, interval, source, start_date, end_date, limit, offset, order)

        return await self._do_query(session, symbol, interval, source, start_date, end_date, limit, offset, order)

    async def _do_query(
        self,
        session: AsyncSession,
        symbol: str,
        interval: str,
        source: str | None,
        start_date: datetime | None,
        end_date: datetime | None,
        limit: int,
        offset: int,
        order: str,
    ) -> list[OHLCVData]:
        order_clause = "ASC" if order == "asc" else "DESC"
        query = text(self.QUERY_SQL.text.format(order=order_clause))

        result = await session.execute(
            query,
            {
                "symbol": symbol,
                "interval": interval,
                "source": source,
                "start_date": start_date,
                "end_date": end_date,
                "limit": limit,
                "offset": offset,
            },
        )
        rows = result.fetchall()
        return [
            OHLCVData(
                symbol=row[0],
                source=row[1],
                interval=row[2],
                timestamp=row[3],
                open=float(row[4]),
                high=float(row[5]),
                low=float(row[6]),
                close=float(row[7]),
                volume=float(row[8]),
                vwap=float(row[9]) if row[9] is not None else None,
                trades_count=int(row[10]) if row[10] is not None else None,
            )
            for row in rows
        ]

    async def get_summary(
        self,
        symbol: str,
        interval: str = "1d",
        session: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        """Get aggregate statistics for a symbol/interval."""
        if session is None:
            if self._session_factory is None:
                return None
            async with self._session_factory() as s:
                return await self._do_summary(s, symbol, interval)

        return await self._do_summary(session, symbol, interval)

    async def _do_summary(self, session: AsyncSession, symbol: str, interval: str) -> dict[str, Any] | None:
        result = await session.execute(
            self.SUMMARY_SQL,
            {"symbol": symbol, "interval": interval},
        )
        row = result.fetchone()
        if row is None:
            return None
        return {
            "symbol": row[0],
            "source": row[1],
            "interval": row[2],
            "count": row[3],
            "first_timestamp": row[4],
            "last_timestamp": row[5],
            "high": float(row[6]) if row[6] else None,
            "low": float(row[7]) if row[7] else None,
            "avg_close": float(row[8]) if row[8] else None,
            "total_volume": float(row[9]) if row[9] else 0.0,
        }

    async def check_data_exists(
        self,
        symbol: str,
        source: str,
        interval: str,
        session: AsyncSession | None = None,
    ) -> bool:
        """Check if data already exists for a symbol/source/interval combo."""
        if session is None:
            if self._session_factory is None:
                return False
            async with self._session_factory() as s:
                return await self._do_check_exists(s, symbol, source, interval)

        return await self._do_check_exists(session, symbol, source, interval)

    async def _do_check_exists(self, session: AsyncSession, symbol: str, source: str, interval: str) -> bool:
        result = await session.execute(
            self.CHECK_EXISTS_SQL,
            {"symbol": symbol, "source": source, "interval": interval},
        )
        count = result.scalar()
        return count is not None and count > 0
