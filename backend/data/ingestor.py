"""Market data ingestion orchestrator.

Coordinates the full data pipeline:
1. Check cache → return if fresh
2. Fetch from source if cache miss
3. Store in database
4. Update cache
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.cache import MarketDataCache, NullCache
from backend.data.models import (
    MarketDataQuery,
    MarketDataRequest,
    MarketDataResult,
    Source,
)
from backend.data.repository import MarketDataRepository
from backend.data.sources.registry import SourceRegistry, create_default_registry

logger = logging.getLogger("ares.data.ingestor")


class MarketDataIngestor:
    """Orchestrates market data ingestion from source to cache to database.

    Flow:
    1. Cache check → return cached data if available and fresh
    2. Source fetch → query the external API
    3. DB store → persist to market_data table
    4. Cache update → prime the cache for next read
    """

    def __init__(
        self,
        source_registry: SourceRegistry | None = None,
        cache: MarketDataCache | None = None,
        repository: MarketDataRepository | None = None,
    ) -> None:
        self.sources = source_registry or create_default_registry()
        self.cache = cache or NullCache()
        self.repository = repository or MarketDataRepository()
        self._stats: dict[str, Any] = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0,
        }

    async def ingest(
        self,
        request: MarketDataRequest,
        session: AsyncSession | None = None,
    ) -> MarketDataResult:
        """Execute a full ingestion cycle for a data request.

        Args:
            request: Parameters for what data to fetch.
            session: Optional database session. If None, creates one.

        Returns:
            MarketDataResult with counts for cached/source/stored data.
        """
        start = time.monotonic()
        self._stats["total_requests"] += 1

        result = MarketDataResult(
            symbol=request.symbol,
            source=request.source,
            interval=request.interval,
            start_date=request.start_date,
            end_date=request.end_date,
        )

        # 1. Try cache first
        cached = await self.cache.get_candles(
            source=request.source,
            symbol=request.symbol,
            interval=request.interval,
            start_date=request.start_date,
            end_date=request.end_date,
        )

        if cached is not None and len(cached) >= min(request.limit, 10):
            self._stats["cache_hits"] += 1
            result.cached = True
            result.count = len(cached)
            result.from_cache = len(cached)
            result.candles = cached
            result.elapsed_ms = int((time.monotonic() - start) * 1000)
            return result

        self._stats["cache_misses"] += 1

        # 2. Fetch from source
        try:
            source = self.sources.get(request.source)
            candles = await source.fetch_ohlcv(
                symbol=request.symbol,
                interval=request.interval,
                start_date=request.start_date,
                end_date=request.end_date,
                limit=request.limit,
            )
        except Exception as e:
            self._stats["errors"] += 1
            result.errors.append(f"Source fetch failed: {e!s}")
            result.elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.error("Source fetch error", extra={"error": str(e), "request": request.model_dump()})
            return result

        result.from_source = len(candles)

        if not candles:
            result.elapsed_ms = int((time.monotonic() - start) * 1000)
            return result

        # 3. Store in database
        try:
            stored = await self.repository.insert_ohlcv(candles, session=session)
            result.stored = stored
        except Exception as e:
            self._stats["errors"] += 1
            result.errors.append(f"DB store failed: {e!s}")
            logger.error("DB store error", extra={"error": str(e)}, exc_info=True)
            # Still try to cache what we fetched

        # 4. Cache what we fetched
        try:
            await self.cache.set_candles(candles)
        except Exception as e:
            logger.warning("Cache write failed", extra={"error": str(e)})

        result.count = len(candles)
        result.candles = candles
        result.elapsed_ms = int((time.monotonic() - start) * 1000)
        return result

    async def ingest_batch(
        self,
        symbols: list[str],
        source: str = "yahoo",
        interval: str = "1d",
        limit: int = 100,
    ) -> list[MarketDataResult]:
        """Ingest data for multiple symbols from the same source."""
        results: list[MarketDataResult] = []
        for symbol in symbols:
            request = MarketDataRequest(
                symbol=symbol,
                source=source,
                interval=interval,
                limit=limit,
            )
            result = await self.ingest(request)
            results.append(result)
        return results

    async def refresh(
        self,
        symbol: str,
        source: str = "yahoo",
        interval: str = "1d",
    ) -> MarketDataResult:
        """Force-refresh cached data by invalidating cache first."""
        await self.cache.invalidate(source, symbol, interval)
        return await self.ingest(
            MarketDataRequest(symbol=symbol, source=source, interval=interval)
        )

    def get_stats(self) -> dict[str, Any]:
        """Get ingestion statistics."""
        return dict(self._stats)

    async def close(self) -> None:
        """Close all source connections."""
        await self.sources.close_all()
