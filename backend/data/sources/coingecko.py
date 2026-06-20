"""CoinGecko market data source."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

import httpx

from backend.data.models import OHLCVData
from backend.data.sources.base import BaseDataSource

# CoinGecko API endpoints
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_OHLCV = f"{COINGECKO_BASE}/coins/{{coin_id}}/ohlc"
COINGECKO_PRICE = f"{COINGECKO_BASE}/simple/price"

# Days param for CoinGecko OHLC endpoint
INTERVAL_TO_DAYS = {
    "1m": 1,
    "5m": 1,
    "15m": 1,
    "30m": 1,
    "1h": 7,
    "4h": 30,
    "1d": 90,
    "1w": 365,
    "1mo": 365,
}

# CoinGecko vs. our internal interval
INTERVAL_MAP = {
    "1m": "minute",
    "5m": "minute",
    "15m": "minute",
    "30m": "minute",
    "1h": "hourly",
    "4h": "hourly",
    "1d": "daily",
    "1w": "daily",
    "1mo": "daily",
}

# Canonical crypto symbol -> CoinGecko coin id
SYMBOL_TO_COINGECKO_ID: dict[str, str] = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "XRP-USD": "ripple",
    "ADA-USD": "cardano",
    "DOGE-USD": "dogecoin",
    "DOT-USD": "polkadot",
    "AVAX-USD": "avalanche-2",
    "LINK-USD": "chainlink",
    "MATIC-USD": "matic-network",
    "UNI-USD": "uniswap",
    "ATOM-USD": "cosmos",
    "LTC-USD": "litecoin",
    "BCH-USD": "bitcoin-cash",
    "TRX-USD": "tron",
}

# Reverse mapping
COINGECKO_ID_TO_SYMBOL: dict[str, str] = {
    v: k for k, v in SYMBOL_TO_COINGECKO_ID.items()
}


class CoinGeckoSource(BaseDataSource):
    """Market data from CoinGecko public API.

    Note: Free tier is rate-limited to 10-30 calls/minute and returns
    historical OHLC data only. For real-time, use Binance instead.
    """

    source_name = "coingecko"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=30.0,
            headers={"Accept": "application/json"},
        )
        self._last_request: float = 0.0

    async def fetch_ohlcv(
        self,
        symbol: str,
        interval: str = "1d",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
    ) -> list[OHLCVData]:
        coin_id = self.normalize_symbol(symbol)
        if coin_id == symbol:
            return []  # Could not map to CoinGecko coin id

        days = self._resolve_days(interval, start_date, end_date, limit)

        # CoinGecko OHLC endpoint: returns [timestamp_ms, open, high, low, close]
        params: dict[str, Any] = {
            "vs_currency": "usd",
            "days": str(days),
        }

        await self._rate_limit()

        url = COINGECKO_OHLCV.format(coin_id=coin_id)
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        raw = response.json()

        return self._parse_ohlcv(raw, symbol, interval)

    def normalize_symbol(self, symbol: str) -> str:
        """Convert canonical symbol to CoinGecko coin id."""
        return SYMBOL_TO_COINGECKO_ID.get(symbol, symbol)

    def denormalize_symbol(self, symbol: str) -> str:
        """Convert CoinGecko coin id back to canonical symbol."""
        return COINGECKO_ID_TO_SYMBOL.get(symbol, symbol)

    def _resolve_days(
        self,
        interval: str,
        start_date: datetime | None,
        end_date: datetime | None,
        limit: int,
    ) -> int:
        """Resolve CoinGecko 'days' parameter."""
        if start_date and end_date:
            delta = (end_date - start_date).days
            return max(1, delta + 1)

        if start_date:
            return max(1, (datetime.utcnow() - start_date).days + 1)

        base = INTERVAL_TO_DAYS.get(interval, 90)
        return min(base, 365)

    def _parse_ohlcv(
        self,
        raw: list[list],
        symbol: str,
        interval: str,
    ) -> list[OHLCVData]:
        """Parse CoinGecko OHLC response into OHLCVData list.

        Format: [[timestamp_ms, open, high, low, close], ...]
        """
        candles: list[OHLCVData] = []
        for item in raw:
            if len(item) < 5:
                continue
            ts_ms, o, h, lo, c = item[:5]
            candles.append(
                OHLCVData(
                    symbol=symbol,
                    source=self.source_name,
                    interval=interval,
                    timestamp=datetime.fromtimestamp(ts_ms / 1000),
                    open=float(o),
                    high=float(h),
                    low=float(lo),
                    close=float(c),
                    volume=0.0,
                )
            )
        return candles

    async def _rate_limit(self) -> None:
        """Rate-limit: minimum 2s between requests (free tier)."""
        now = time.monotonic()
        since_last = now - self._last_request
        if since_last < 2.0:
            await asyncio.sleep(2.0 - since_last)
        self._last_request = time.monotonic()

    async def close(self) -> None:
        await self._client.aclose()
