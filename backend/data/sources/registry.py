"""Source registry for market data providers."""

from __future__ import annotations

from typing import Any

from backend.data.models import Source
from backend.data.sources.base import BaseDataSource
from backend.data.sources.binance import BinanceSource
from backend.data.sources.coingecko import CoinGeckoSource
from backend.data.sources.yahoo import YahooFinanceSource


class SourceRegistry:
    """Registry of available market data sources.

    Provides lookup by source name and manages lifecycle.
    """

    def __init__(self) -> None:
        self._sources: dict[str, BaseDataSource] = {}

    def register(self, source: BaseDataSource) -> None:
        """Register a data source instance."""
        self._sources[source.source_name] = source

    def get(self, name: str) -> BaseDataSource:
        """Get a registered source by name."""
        if name not in self._sources:
            raise KeyError(
                f"Unknown data source '{name}'. "
                f"Available: {list(self._sources.keys())}"
            )
        return self._sources[name]

    def list_sources(self) -> list[str]:
        """List all registered source names."""
        return list(self._sources.keys())

    async def close_all(self) -> None:
        """Close all registered source connections."""
        for source in self._sources.values():
            try:
                await source.close()
            except Exception:
                pass


def create_default_registry() -> SourceRegistry:
    """Create the default registry with all built-in sources."""
    registry = SourceRegistry()
    registry.register(YahooFinanceSource())
    registry.register(CoinGeckoSource())
    registry.register(BinanceSource())
    return registry
