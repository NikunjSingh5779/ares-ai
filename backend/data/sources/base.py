"""Abstract base class for market data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from backend.data.models import OHLCVData


class BaseDataSource(ABC):
    """Abstract interface for a market data provider.

    Every source (Yahoo, CoinGecko, Binance) implements this interface.
    The Ingestor uses this to fetch data without caring which source.
    """

    source_name: str = ""

    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        interval: str = "1d",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
    ) -> list[OHLCVData]:
        """Fetch OHLCV candlestick data from the source.

        Args:
            symbol: Ticker symbol in source-specific format.
            interval: Candle interval (1m, 5m, 1h, 1d, etc.).
            start_date: Fetch data from this date (inclusive).
            end_date: Fetch data until this date (inclusive).
            limit: Maximum number of candles.

        Returns:
            List of OHLCVData objects, ordered oldest-first.
        """
        ...

    @abstractmethod
    def normalize_symbol(self, symbol: str) -> str:
        """Convert a canonical symbol to this source's format.

        E.g., canonical 'BTC-USD' → Yahoo 'BTC-USD', Binance 'BTCUSDT'.
        """
        ...

    @abstractmethod
    def denormalize_symbol(self, symbol: str) -> str:
        """Convert this source's symbol back to canonical form.

        E.g., Binance 'BTCUSDT' → canonical 'BTC-USD'.
        """
        ...

    def validate_response(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Validate and clean raw API response data.

        Override for source-specific sanitization.
        """
        return data
