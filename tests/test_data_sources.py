"""Tests for market data sources (Yahoo, CoinGecko, Binance)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock

from backend.data.sources.binance import BinanceSource
from backend.data.sources.coingecko import CoinGeckoSource
from backend.data.sources.registry import SourceRegistry, create_default_registry
from backend.data.sources.yahoo import YahooFinanceSource


# ---------------------------------------------------------------------------
# Yahoo Finance Source
# ---------------------------------------------------------------------------

YAHOO_MOCK_RESPONSE = {
    "chart": {
        "result": [
            {
                "timestamp": [1704067200, 1704153600, 1704240000],
                "indicators": {
                    "quote": [
                        {
                            "open": [100.0, 101.0, 102.0],
                            "high": [105.0, 106.0, 107.0],
                            "low": [99.0, 100.0, 101.0],
                            "close": [104.0, 105.0, 106.0],
                            "volume": [10000, 11000, 12000],
                        }
                    ],
                    "adjclose": [
                        {"adjclose": [104.0, 105.0, 106.0]}
                    ],
                },
            }
        ]
    }
}


class TestYahooFinanceSource:
    @pytest.fixture
    def source(self) -> YahooFinanceSource:
        return YahooFinanceSource()

    async def test_fetch_ohlcv(self, source: YahooFinanceSource, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=httpx.URL(
                "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"
                "?interval=1d&includePrePost=false&range=1mo"
            ),
            json=YAHOO_MOCK_RESPONSE,
        )

        candles = await source.fetch_ohlcv(symbol="AAPL", interval="1d", limit=3)

        assert len(candles) == 3
        assert candles[0].symbol == "AAPL"
        assert candles[0].open == 100.0
        assert candles[0].close == 104.0
        assert candles[2].close == 106.0

    async def test_fetch_ohlcv_empty_response(self, source: YahooFinanceSource, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=httpx.URL(
                "https://query1.finance.yahoo.com/v8/finance/chart/BADSYM"
                "?interval=1d&includePrePost=false&range=6mo"
            ),
            json={"chart": {"result": []}},
        )

        candles = await source.fetch_ohlcv(symbol="BADSYM", interval="1d")
        assert len(candles) == 0

    async def test_fetch_ohlcv_missing_data(self, source: YahooFinanceSource, httpx_mock: HTTPXMock) -> None:
        """Null values in quote data should be skipped."""
        partial_data = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1704067200, 1704153600, 1704240000],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.0, None, 102.0],
                                    "high": [105.0, None, 107.0],
                                    "low": [99.0, None, 101.0],
                                    "close": [104.0, None, 106.0],
                                    "volume": [10000, None, 12000],
                                }
                            ],
                            "adjclose": [{"adjclose": [104.0, None, 106.0]}],
                        },
                    }
                ]
            }
        }
        httpx_mock.add_response(
            url=httpx.URL(
                "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"
                "?interval=1d&includePrePost=false&range=6mo"
            ),
            json=partial_data,
        )

        candles = await source.fetch_ohlcv(symbol="AAPL", interval="1d")
        assert len(candles) == 2  # middle candle skipped

    async def test_normalize_symbol(self, source: YahooFinanceSource) -> None:
        assert source.normalize_symbol("BTC-USD") == "BTC-USD"
        assert source.denormalize_symbol("BTC-USD") == "BTC-USD"


# ---------------------------------------------------------------------------
# CoinGecko Source
# ---------------------------------------------------------------------------

COINGECKO_MOCK_RESPONSE = [
    [1704067200000, 42000, 42500, 41500, 42200],
    [1704153600000, 42200, 43000, 41800, 42800],
    [1704240000000, 42800, 43200, 42600, 43000],
]


class TestCoinGeckoSource:
    @pytest.fixture
    def source(self) -> CoinGeckoSource:
        return CoinGeckoSource()

    async def test_fetch_ohlcv(self, source: CoinGeckoSource, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=httpx.URL(
                "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc"
                "?vs_currency=usd&days=90"
            ),
            json=COINGECKO_MOCK_RESPONSE,
        )

        candles = await source.fetch_ohlcv(symbol="BTC-USD", interval="1d", limit=3)

        assert len(candles) == 3
        assert candles[0].symbol == "BTC-USD"
        assert candles[0].open == 42000.0
        assert candles[0].close == 42200.0
        assert candles[0].volume == 0.0  # CoinGecko OHLC doesn't include volume

    async def test_fetch_ohlcv_unknown_symbol(self, source: CoinGeckoSource) -> None:
        candles = await source.fetch_ohlcv(symbol="UNKNOWN-USD")
        assert len(candles) == 0

    async def test_normalize_symbol(self, source: CoinGeckoSource) -> None:
        assert source.normalize_symbol("BTC-USD") == "bitcoin"
        assert source.normalize_symbol("ETH-USD") == "ethereum"
        assert source.normalize_symbol("AAPL") == "AAPL"  # not found

    async def test_denormalize_symbol(self, source: CoinGeckoSource) -> None:
        assert source.denormalize_symbol("bitcoin") == "BTC-USD"
        assert source.denormalize_symbol("unknown") == "unknown"


# ---------------------------------------------------------------------------
# Binance Source
# ---------------------------------------------------------------------------

BINANCE_MOCK_RESPONSE = [
    [
        1704067200000,
        "42000.00",
        "42500.00",
        "41500.00",
        "42200.00",
        "100.5",
        1704153600000,
        "4200000.0",
        500,
        "50.0",
        "2100000.0",
        "0",
    ],
    [
        1704153600000,
        "42200.00",
        "43000.00",
        "41800.00",
        "42800.00",
        "150.75",
        1704240000000,
        "6400000.0",
        750,
        "75.0",
        "3200000.0",
        "0",
    ],
]


class TestBinanceSource:
    @pytest.fixture
    def source(self) -> BinanceSource:
        return BinanceSource()

    async def test_fetch_ohlcv(self, source: BinanceSource, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=httpx.URL(
                "https://api.binance.com/api/v3/klines"
                "?symbol=BTCUSDT&interval=1d&limit=2"
            ),
            json=BINANCE_MOCK_RESPONSE,
        )

        candles = await source.fetch_ohlcv(symbol="BTC-USD", interval="1d", limit=2)

        assert len(candles) == 2
        assert candles[0].symbol == "BTC-USD"
        assert candles[0].open == 42000.0
        assert candles[0].high == 42500.0
        assert candles[0].volume == 100.5
        assert candles[0].vwap == 4200000.0
        assert candles[0].trades_count == 500

    async def test_normalize_symbol(self, source: BinanceSource) -> None:
        assert source.normalize_symbol("BTC-USD") == "BTCUSDT"
        assert source.normalize_symbol("ETH-USD") == "ETHUSDT"

    async def test_denormalize_symbol(self, source: BinanceSource) -> None:
        assert source.denormalize_symbol("BTCUSDT") == "BTC-USD"
        assert source.denormalize_symbol("BTC-USD") == "BTC-USD"


# ---------------------------------------------------------------------------
# Source Registry
# ---------------------------------------------------------------------------


class TestSourceRegistry:
    def test_create_default_registry(self) -> None:
        registry = create_default_registry()
        sources = registry.list_sources()
        assert "yahoo" in sources
        assert "coingecko" in sources
        assert "binance" in sources

    def test_get_source(self) -> None:
        registry = create_default_registry()
        source = registry.get("yahoo")
        assert source.source_name == "yahoo"

    def test_get_unknown_source(self) -> None:
        registry = create_default_registry()
        with pytest.raises(KeyError, match="Unknown data source"):
            registry.get("nonexistent")

    def test_register_custom_source(self) -> None:
        registry = SourceRegistry()
        source = BinanceSource()
        registry.register(source)
        assert registry.get("binance").source_name == "binance"
