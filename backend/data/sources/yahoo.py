"""Yahoo Finance market data source."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from backend.data.models import OHLCVData
from backend.data.sources.base import BaseDataSource

# Yahoo Finance v8 chart API endpoint
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# Interval mapping: our internal → Yahoo API parameter
INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "4h": "1d",  # Yahoo doesn't have 4h; we'll downsample on request
    "1d": "1d",
    "1w": "1wk",
    "1mo": "1mo",
}

# Max candles per request by interval (Yahoo limits)
MAX_PER_REQUEST = {
    "1m": 7,  # 7 days of 1m
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "1h": 730,
    "1d": 8000,
    "1w": 2000,
    "1mo": 2000,
}

CANONICAL_PREFIXES = ("^",)


class YahooFinanceSource(BaseDataSource):
    """Market data from Yahoo Finance v8 chart API."""

    source_name = "yahoo"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "Mozilla/5.0"},
        )

    async def fetch_ohlcv(
        self,
        symbol: str,
        interval: str = "1d",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
    ) -> list[OHLCVData]:
        yahoo_interval = INTERVAL_MAP.get(interval, "1d")
        range_param = self._resolve_range(interval, limit)
        params: dict[str, Any] = {
            "interval": yahoo_interval,
            "includePrePost": False,
        }

        if start_date:
            params["period1"] = int(start_date.timestamp())
        if end_date:
            params["period2"] = int(end_date.timestamp())

        if not start_date and not end_date:
            params["range"] = range_param

        url = YAHOO_CHART_URL.format(symbol=symbol.replace("-", "-"))
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        return self._parse_chart_response(data, symbol, interval)

    def normalize_symbol(self, symbol: str) -> str:
        """Yahoo format is already canonical for most assets."""
        return symbol

    def denormalize_symbol(self, symbol: str) -> str:
        """Yahoo symbols are canonical."""
        return symbol

    def _resolve_range(self, interval: str, limit: int) -> str:
        """Map interval + limit to a Yahoo 'range' parameter."""
        if interval in ("1d", "1w", "1mo"):
            if limit <= 30:
                return "1mo"
            elif limit <= 180:
                return "6mo"
            elif limit <= 365:
                return "1y"
            elif limit <= 1825:
                return "5y"
            else:
                return "max"
        elif interval in ("1h", "4h"):
            return "1mo" if limit <= 730 else "3mo"
        else:  # minute-level
            return "5d" if limit <= 7 else "1mo"

    def _parse_chart_response(
        self,
        raw: dict[str, Any],
        symbol: str,
        interval: str,
    ) -> list[OHLCVData]:
        """Parse Yahoo Finance v8 chart API response into OHLCVData list."""
        result = raw.get("chart", {}).get("result", [])
        if not result:
            return []

        timestamps = result[0].get("timestamp", [])
        quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
        adjclose = result[0].get("indicators", {}).get("adjclose", [{}])

        opens = quotes.get("open", [])
        highs = quotes.get("high", [])
        lows = quotes.get("low", [])
        closes = quotes.get("close", [])
        volumes = quotes.get("volume", [])
        adjclose_data = adjclose[0].get("adjclose", []) if adjclose else []

        candles: list[OHLCVData] = []
        for i, ts in enumerate(timestamps):
            o = opens[i] if i < len(opens) else None
            h = highs[i] if i < len(highs) else None
            lo = lows[i] if i < len(lows) else None
            c = closes[i] if i < len(closes) else None
            v = volumes[i] if i < len(volumes) else None

            if o is None or h is None or lo is None or c is None:
                continue

            vwap = adjclose_data[i] if i < len(adjclose_data) else None

            candles.append(
                OHLCVData(
                    symbol=symbol,
                    source=self.source_name,
                    interval=interval,
                    timestamp=datetime.fromtimestamp(ts),
                    open=float(o),
                    high=float(h),
                    low=float(lo),
                    close=float(c),
                    volume=float(v) if v is not None else 0.0,
                    vwap=float(vwap) if vwap is not None else None,
                )
            )

        return candles

    async def close(self) -> None:
        await self._client.aclose()
