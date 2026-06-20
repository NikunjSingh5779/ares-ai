"""Binance public API market data source."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from backend.data.models import OHLCVData
from backend.data.sources.base import BaseDataSource

BINANCE_BASE = "https://api.binance.com"
BINANCE_KLINES = f"{BINANCE_BASE}/api/v3/klines"
BINANCE_EXCHANGE_INFO = f"{BINANCE_BASE}/api/v3/exchangeInfo"

# Binance kline interval format
INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
    "1mo": "1M",
}

# Max candles per request (Binance limits to 1000)
MAX_PER_REQUEST = 1000

# Canonical symbol → Binance symbol
SYMBOL_TO_BINANCE: dict[str, str] = {
    "BTC-USD": "BTCUSDT",
    "ETH-USD": "ETHUSDT",
    "SOL-USD": "SOLUSDT",
    "XRP-USD": "XRPUSDT",
    "ADA-USD": "ADAUSDT",
    "DOGE-USD": "DOGEUSDT",
    "DOT-USD": "DOTUSDT",
    "AVAX-USD": "AVAXUSDT",
    "LINK-USD": "LINKUSDT",
    "MATIC-USD": "MATICUSDT",
    "UNI-USD": "UNIUSDT",
    "ATOM-USD": "ATOMUSDT",
    "LTC-USD": "LTCUSDT",
    "BCH-USD": "BCHUSDT",
    "TRX-USD": "TRXUSDT",
    "BNB-USD": "BNBUSDT",
    "ETH-BTC": "ETHBTC",
}

# Reverse mapping for denormalization
BINANCE_TO_SYMBOL: dict[str, str] = {v: k for k, v in SYMBOL_TO_BINANCE.items()}


class BinanceSource(BaseDataSource):
    """Market data from Binance public REST API.

    Binance has generous rate limits (1200 weight/min) and no API key
    needed for public endpoints. Best source for crypto real-time data.
    """

    source_name = "binance"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    async def fetch_ohlcv(
        self,
        symbol: str,
        interval: str = "1d",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
    ) -> list[OHLCVData]:
        binance_symbol = self.normalize_symbol(symbol)
        if binance_symbol == symbol and "-" in symbol:
            return []  # Could not map to a Binance symbol

        binance_interval = INTERVAL_MAP.get(interval, "1d")
        capped_limit = min(limit, MAX_PER_REQUEST)

        params: dict[str, Any] = {
            "symbol": binance_symbol,
            "interval": binance_interval,
            "limit": capped_limit,
        }

        if start_date:
            params["startTime"] = int(start_date.timestamp() * 1000)
        if end_date:
            params["endTime"] = int(end_date.timestamp() * 1000)

        response = await self._client.get(BINANCE_KLINES, params=params)
        response.raise_for_status()
        raw = response.json()

        return self._parse_klines(raw, symbol, interval)

    def normalize_symbol(self, symbol: str) -> str:
        """Convert canonical symbol to Binance format."""
        return SYMBOL_TO_BINANCE.get(symbol, symbol)

    def denormalize_symbol(self, symbol: str) -> str:
        """Convert Binance symbol back to canonical format."""
        return BINANCE_TO_SYMBOL.get(symbol, symbol)

    async def get_exchange_info(self) -> dict[str, Any]:
        """Fetch exchange info (trading pairs, filters, etc.)."""
        response = await self._client.get(BINANCE_EXCHANGE_INFO)
        response.raise_for_status()
        return response.json()

    def _parse_klines(
        self,
        raw: list[list],
        symbol: str,
        interval: str,
    ) -> list[OHLCVData]:
        """Parse Binance kline response into OHLCVData list.

        Binance kline format:
        [open_time, open, high, low, close, volume, close_time,
         quote_asset_volume, number_of_trades, taker_buy_base_vol,
         taker_buy_quote_vol, ignore]
        """
        candles: list[OHLCVData] = []
        for k in raw:
            if len(k) < 11:
                continue
            candles.append(
                OHLCVData(
                    symbol=symbol,
                    source=self.source_name,
                    interval=interval,
                    timestamp=datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc),
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    vwap=float(k[7]) if k[7] else None,  # quote asset volume
                    trades_count=int(k[8]),
                )
            )
        return candles

    async def close(self) -> None:
        await self._client.aclose()
