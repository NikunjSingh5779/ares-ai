"""Tests for the read-only market candles endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.data.models import OHLCVData
from backend.data.sources.binance import BinanceSource
from backend.data.sources.coingecko import CoinGeckoSource
from backend.data.sources.yahoo import YahooFinanceSource
from backend.routers import market


class FakeSource:
    """Minimal stand-in for a market data source."""

    source_name = "yahoo"

    def __init__(
        self,
        candles: list[OHLCVData] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.candles = candles or []
        self.error = error
        self.closed = False
        self.fetch_kwargs: dict[str, Any] = {}

    async def fetch_ohlcv(self, **kwargs: Any) -> list[OHLCVData]:
        self.fetch_kwargs = kwargs
        if self.error is not None:
            raise self.error
        return self.candles

    async def close(self) -> None:
        self.closed = True


def _candle(index: int, **overrides: Any) -> OHLCVData:
    values: dict[str, Any] = {
        "symbol": "BTC-USD",
        "source": "yahoo",
        "interval": "1d",
        "timestamp": datetime(2024, 1, 1) + timedelta(days=index),
        "open": 100.0 + index,
        "high": 105.0 + index,
        "low": 99.0 + index,
        "close": 104.0 + index,
        "volume": 1000.0 + index,
    }
    values.update(overrides)
    return OHLCVData(**values)


@pytest.fixture
def app() -> FastAPI:
    result = FastAPI()
    result.include_router(market.router)
    return result


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_source(monkeypatch: pytest.MonkeyPatch) -> FakeSource:
    source = FakeSource(candles=[_candle(i) for i in range(5)])
    monkeypatch.setattr(market, "_source_for", lambda symbol, requested: source)
    return source


class TestCandlesEndpoint:
    def test_returns_ascending_utc_epoch_candles(self, client: TestClient, fake_source: FakeSource) -> None:
        fake_source.candles = [_candle(2), _candle(0), _candle(1)]

        response = client.get("/api/v1/market/candles?symbol=BTC-USD&interval=1d")

        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "BTC-USD"
        assert body["interval"] == "1d"
        assert body["source"] == "binance"
        assert body["count"] == 3
        assert [candle["time"] for candle in body["candles"]] == [
            1704067200,
            1704153600,
            1704240000,
        ]
        assert body["candles"][0]["open"] == 100.0
        assert fake_source.closed is True
        assert fake_source.fetch_kwargs == {"symbol": "BTC-USD", "interval": "1d", "limit": 120}

    def test_returns_only_the_most_recent_limit(self, client: TestClient, fake_source: FakeSource) -> None:
        response = client.get("/api/v1/market/candles?symbol=BTC-USD&limit=2")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert [candle["time"] for candle in body["candles"]] == [1704326400, 1704412800]

    def test_collapses_duplicate_timestamps(self, client: TestClient, fake_source: FakeSource) -> None:
        fake_source.candles = [
            _candle(0, close=101.0),
            _candle(0, close=999.0),
        ]

        response = client.get("/api/v1/market/candles?symbol=AAPL")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["candles"][0]["close"] == 999.0

    def test_empty_result_returns_404(self, client: TestClient, fake_source: FakeSource) -> None:
        fake_source.candles = []

        response = client.get("/api/v1/market/candles?symbol=BADSYM")

        assert response.status_code == 404
        assert "No market data" in response.json()["detail"]
        assert fake_source.closed is True

    def test_invalid_interval_returns_422(self, client: TestClient, fake_source: FakeSource) -> None:
        response = client.get("/api/v1/market/candles?symbol=BTC-USD&interval=3s")

        assert response.status_code == 422
        assert "Invalid interval" in response.json()["detail"]

    def test_invalid_source_returns_422(self, client: TestClient, fake_source: FakeSource) -> None:
        response = client.get("/api/v1/market/candles?symbol=BTC-USD&source=paid-feed")

        assert response.status_code == 422
        assert "Invalid source" in response.json()["detail"]

    def test_limit_out_of_bounds_returns_422(self, client: TestClient, fake_source: FakeSource) -> None:
        assert client.get("/api/v1/market/candles?symbol=BTC-USD&limit=0").status_code == 422
        assert client.get("/api/v1/market/candles?symbol=BTC-USD&limit=501").status_code == 422

    def test_upstream_http_error_returns_502(self, client: TestClient, fake_source: FakeSource) -> None:
        fake_source.error = httpx.ConnectError("upstream down")

        response = client.get("/api/v1/market/candles?symbol=BTC-USD")

        assert response.status_code == 502
        assert "Market data source failed" in response.json()["detail"]
        assert fake_source.closed is True

    def test_timeout_returns_504(
        self, client: TestClient, fake_source: FakeSource, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class SlowSource(FakeSource):
            async def fetch_ohlcv(self, **kwargs: Any) -> list[OHLCVData]:
                raise TimeoutError

        slow = SlowSource()
        monkeypatch.setattr(market, "_source_for", lambda symbol, requested: slow)

        response = client.get("/api/v1/market/candles?symbol=BTC-USD")

        assert response.status_code == 504
        assert "timed out" in response.json()["detail"]
        assert slow.closed is True


class TestSourceSelection:
    async def test_crypto_defaults_to_binance(self) -> None:
        source = market._source_for("BTC-USD", None)
        try:
            assert isinstance(source, BinanceSource)
        finally:
            await source.close()

    async def test_equity_defaults_to_yahoo(self) -> None:
        source = market._source_for("AAPL", None)
        try:
            assert isinstance(source, YahooFinanceSource)
        finally:
            await source.close()

    async def test_explicit_yahoo_is_honored_for_crypto(self) -> None:
        source = market._source_for("BTC-USD", "yahoo")
        try:
            assert isinstance(source, YahooFinanceSource)
        finally:
            await source.close()

    async def test_explicit_coingecko_is_honored(self) -> None:
        source = market._source_for("BTC-USD", "coingecko")
        try:
            assert isinstance(source, CoinGeckoSource)
        finally:
            await source.close()
