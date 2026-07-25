"""Tests for the Zerodha stub connector.

Verifies that lifecycle methods work and that every order method
raises NotImplementedError with a clear message — the connector
is explicitly a stub, not an incomplete implementation.
"""

from __future__ import annotations

import pytest

from live_trading.exchange.base import ExchangeConnector
from live_trading.exchange.zerodha import ZerodhaStubConnector


@pytest.fixture
def connector() -> ZerodhaStubConnector:
    return ZerodhaStubConnector({})


class TestZerodhaStubConnector:

    # ── Lifecycle ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_connect(self, connector: ZerodhaStubConnector) -> None:
        assert await connector.connect() is True
        assert connector.is_connected is True

    @pytest.mark.asyncio
    async def test_disconnect(self, connector: ZerodhaStubConnector) -> None:
        await connector.connect()
        await connector.disconnect()
        assert connector.is_connected is False

    @pytest.mark.asyncio
    async def test_is_connected_initial_state(self, connector: ZerodhaStubConnector) -> None:
        assert connector.is_connected is False

    # ── Balance ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_balance_returns_empty(self, connector: ZerodhaStubConnector) -> None:
        balance = await connector.get_balance()
        assert balance.total == {}
        assert balance.free == {}
        assert balance.used == {}

    # ── Market data ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_ticker_returns_stub_shape(self, connector: ZerodhaStubConnector) -> None:
        ticker = await connector.get_ticker("BTC/USDT")
        assert isinstance(ticker, dict)
        assert ticker["symbol"] == "BTC/USDT"
        assert ticker["price"] == 0.0
        assert ticker["volume"] == 0.0

    @pytest.mark.asyncio
    async def test_fetch_ohlcv_returns_empty(self, connector: ZerodhaStubConnector) -> None:
        candles = await connector.fetch_ohlcv("BTC/USDT")
        assert candles == []

    # ── Order methods raise NotImplementedError ──────────────────────

    @pytest.mark.asyncio
    async def test_create_order_raises(self, connector: ZerodhaStubConnector) -> None:
        with pytest.raises(NotImplementedError, match="Zerodha connector is a stub"):
            await connector.create_order("BTC/USDT", "buy", 0.1)

    @pytest.mark.asyncio
    async def test_cancel_order_raises(self, connector: ZerodhaStubConnector) -> None:
        with pytest.raises(NotImplementedError, match="Zerodha connector is a stub"):
            await connector.cancel_order("order-1", "BTC/USDT")

    @pytest.mark.asyncio
    async def test_get_order_status_raises(self, connector: ZerodhaStubConnector) -> None:
        with pytest.raises(NotImplementedError, match="Zerodha connector is a stub"):
            await connector.get_order_status("order-1", "BTC/USDT")

    @pytest.mark.asyncio
    async def test_cancel_all_orders_raises(self, connector: ZerodhaStubConnector) -> None:
        with pytest.raises(NotImplementedError, match="cancel_all_orders not yet implemented"):
            await connector.cancel_all_orders("BTC/USDT")

    # ── ABC conformance ──────────────────────────────────────────────

    def test_is_exchange_connector(self, connector: ZerodhaStubConnector) -> None:
        assert isinstance(connector, ExchangeConnector)
        assert connector.exchange_name == "zerodha"
