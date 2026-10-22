"""Market data API router — read-only candles for the dashboard.

This is a thin read over the existing free data sources. It does not persist
candles, run an agent, or make a trading decision.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Query

from backend.data.models import Interval, Source
from backend.data.sources.base import BaseDataSource
from backend.data.sources.binance import SYMBOL_TO_BINANCE, BinanceSource
from backend.data.sources.coingecko import CoinGeckoSource
from backend.data.sources.yahoo import YahooFinanceSource
from backend.schemas.market import Candle, CandlesResponse

logger = logging.getLogger("ares.api.market")

router = APIRouter(prefix="/api/v1/market", tags=["market"])

DEFAULT_INTERVAL = Interval.DAY_1
DEFAULT_LIMIT = 120
MAX_LIMIT = 500
FETCH_TIMEOUT_SECONDS = 15.0

# Binance covers these canonical symbols; everything else falls back to Yahoo.
_CRYPTO_SYMBOLS = frozenset(SYMBOL_TO_BINANCE)


def _source_for(symbol: str, source: str | None) -> BaseDataSource:
    """Build the free data source for a request.

    Crypto symbols with no explicit source use Binance (real-time public
    pricing). Equities and any explicit source use the requested provider.
    """
    if source == Source.BINANCE or (source is None and symbol in _CRYPTO_SYMBOLS):
        return BinanceSource()
    if source == Source.COINGECKO:
        return CoinGeckoSource()
    return YahooFinanceSource()


def _to_epoch_seconds(timestamp: datetime) -> int:
    """Convert a candle timestamp to UTC epoch seconds.

    Sources return timezone-aware UTC timestamps. A naive value is assumed to
    already be UTC rather than being reinterpreted in the server timezone.
    """
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return int(timestamp.timestamp())


@router.get("/candles", response_model=CandlesResponse)
async def get_candles(
    symbol: Annotated[
        str,
        Query(
            ...,
            min_length=1,
            max_length=20,
            pattern=r"^[A-Za-z0-9^.=:/-]+$",
            description="Ticker symbol, for example BTC-USD or AAPL",
        ),
    ],
    interval: Annotated[
        str,
        Query(description="Candle interval (1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1mo)"),
    ] = DEFAULT_INTERVAL,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_LIMIT, description="Maximum number of recent candles"),
    ] = DEFAULT_LIMIT,
    source: Annotated[
        str | None,
        Query(description="Optional explicit source: yahoo, binance, coingecko"),
    ] = None,
) -> CandlesResponse:
    """Return the most recent candles for a symbol from a free data source."""
    try:
        interval = Interval.validate(interval)
        if source is not None:
            source = Source.validate(source)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    symbol = symbol.upper()
    resolved_source = source or (Source.BINANCE if symbol in _CRYPTO_SYMBOLS else Source.YAHOO)
    client = _source_for(symbol, resolved_source)

    try:
        async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
            candles = await client.fetch_ohlcv(
                symbol=symbol,
                interval=interval,
                limit=limit,
            )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Market data timed out for {symbol}",
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning(
            "Market data source failed",
            extra={"symbol": symbol, "source": resolved_source, "error": str(exc)},
        )
        raise HTTPException(
            status_code=502,
            detail=f"Market data source failed for {symbol}",
        ) from exc
    finally:
        try:
            await client.close()
        except Exception:
            logger.debug("Failed to close market data source", exc_info=True)

    if not candles:
        raise HTTPException(status_code=404, detail=f"No market data for {symbol}")

    # Lightweight Charts requires strictly ascending, unique UTC timestamps.
    by_time: dict[int, Candle] = {}
    for candle in sorted(candles, key=lambda item: item.timestamp)[-limit:]:
        by_time[_to_epoch_seconds(candle.timestamp)] = Candle(
            time=_to_epoch_seconds(candle.timestamp),
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
        )
    ordered = [by_time[key] for key in sorted(by_time)]

    return CandlesResponse(
        symbol=symbol,
        interval=interval,
        source=resolved_source,
        count=len(ordered),
        candles=ordered,
    )
