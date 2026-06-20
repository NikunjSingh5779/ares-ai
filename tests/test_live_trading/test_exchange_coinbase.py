"""Tests for the Coinbase exchange connector (CCXT)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import ccxt
import pytest

from live_trading.exceptions import ExchangeConnectionError, OrderRejectedError
from live_trading.exchange.base import ExchangeBalance, ExchangeOrder
from live_trading.exchange.coinbase import CoinbaseConnector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ccxt_exchange() -> MagicMock:
    """Mock ccxt.coinbase exchange instance."""
    exchange = MagicMock()
    exchange.load_markets = AsyncMock()
    exchange.fetch_balance = AsyncMock(
        return_value={"free": {"BTC": 0.5}, "total": {"BTC": 1.0}, "used": {"BTC": 0.5}}
    )
    exchange.create_order = AsyncMock(return_value={
        "id": "coinbase-order-123",
        "amount": 0.5,
        "price": 50000.0,
        "filled": 0.5,
        "remaining": 0.0,
        "status": "closed",
    })
    exchange.cancel_order = AsyncMock(return_value={"status": "canceled"})
    exchange.fetch_order = AsyncMock(return_value={
        "id": "coinbase-order-123",
        "side": "buy",
        "type": "market",
        "amount": 0.5,
        "price": 50000.0,
        "filled": 0.5,
        "remaining": 0.0,
        "status": "closed",
    })
    exchange.fetch_ticker = AsyncMock(return_value={
        "symbol": "BTC/USD",
        "last": 50000.0,
        "bid": 49900.0,
        "ask": 50100.0,
        "baseVolume": 1000.0,
        "high": 51000.0,
        "low": 49000.0,
        "percentage": 2.5,
    })
    exchange.fetch_ohlcv = AsyncMock(return_value=[
        [1700000000000, 50000.0, 51000.0, 49000.0, 50500.0, 1000.0],
    ])
    return exchange


@pytest.fixture
def connector() -> CoinbaseConnector:
    """CoinbaseConnector with config (no real keys)."""
    return CoinbaseConnector({"api_key": "test-key", "secret": "test-secret"})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCoinbaseConnector:
    def test_init(self):
        conn = CoinbaseConnector({"api_key": "k", "secret": "s"})
        assert conn.exchange_name == "coinbase"
        assert conn.is_connected is False

    @patch("live_trading.exchange.coinbase.ccxt.coinbase")
    async def test_connect_success(self, mock_coinbase_ctor, mock_ccxt_exchange):
        mock_coinbase_ctor.return_value = mock_ccxt_exchange
        conn = CoinbaseConnector({"api_key": "key", "secret": "secret"})

        result = await conn.connect()

        assert result is True
        assert conn.is_connected is True

    @patch("live_trading.exchange.coinbase.ccxt.coinbase")
    async def test_connect_no_keys(self, mock_coinbase_ctor):
        """Should connect without authentication (read-only mode)."""
        mock_exchange = MagicMock()
        mock_exchange.load_markets = AsyncMock()
        mock_coinbase_ctor.return_value = mock_exchange

        conn = CoinbaseConnector({})
        result = await conn.connect()

        assert result is True
        mock_exchange.load_markets.assert_not_called()

    @patch("live_trading.exchange.coinbase.ccxt.coinbase")
    async def test_connect_auth_failure(self, mock_coinbase_ctor):
        mock_exchange = MagicMock()
        mock_exchange.load_markets = AsyncMock(side_effect=ccxt.AuthenticationError("Invalid key"))
        mock_coinbase_ctor.return_value = mock_exchange

        conn = CoinbaseConnector({"api_key": "bad", "secret": "bad"})
        with pytest.raises(ExchangeConnectionError, match="Coinbase authentication failed"):
            await conn.connect()

        assert conn.is_connected is False

    @patch("live_trading.exchange.coinbase.ccxt.coinbase")
    async def test_connect_network_error(self, mock_coinbase_ctor):
        mock_exchange = MagicMock()
        mock_exchange.load_markets = AsyncMock(side_effect=ccxt.NetworkError("timeout"))
        mock_coinbase_ctor.return_value = mock_exchange

        conn = CoinbaseConnector({"api_key": "key", "secret": "secret"})
        with pytest.raises(ExchangeConnectionError, match="Coinbase network error"):
            await conn.connect()

    async def test_disconnect(self, connector):
        connector._connected = True
        connector._client = MagicMock()

        await connector.disconnect()

        assert connector.is_connected is False
        assert connector._client is None

    @patch("live_trading.exchange.coinbase.ccxt.coinbase")
    async def test_get_balance(self, mock_coinbase_ctor, mock_ccxt_exchange):
        mock_coinbase_ctor.return_value = mock_ccxt_exchange
        conn = CoinbaseConnector({"api_key": "key", "secret": "secret"})
        await conn.connect()

        balance = await conn.get_balance()

        assert isinstance(balance, ExchangeBalance)
        assert balance.free.get("BTC") == 0.5

    async def test_get_balance_not_connected(self, connector):
        with pytest.raises(ExchangeConnectionError, match="not connected"):
            await connector.get_balance()

    @patch("live_trading.exchange.coinbase.ccxt.coinbase")
    async def test_create_order(self, mock_coinbase_ctor, mock_ccxt_exchange):
        mock_coinbase_ctor.return_value = mock_ccxt_exchange
        conn = CoinbaseConnector({"api_key": "key", "secret": "secret"})
        await conn.connect()

        order = await conn.create_order("BTC-USD", "buy", 0.5)

        assert isinstance(order, ExchangeOrder)
        assert order.id == "coinbase-order-123"
        assert order.side == "buy"

    @patch("live_trading.exchange.coinbase.ccxt.coinbase")
    async def test_create_order_insufficient_funds(self, mock_coinbase_ctor):
        exchange = MagicMock()
        exchange.load_markets = AsyncMock()
        exchange.fetch_balance = AsyncMock(return_value={"free": {}, "total": {}, "used": {}})
        exchange.create_order = AsyncMock(side_effect=ccxt.InsufficientFunds("low balance"))
        mock_coinbase_ctor.return_value = exchange

        conn = CoinbaseConnector({"api_key": "key", "secret": "secret"})
        await conn.connect()

        with pytest.raises(OrderRejectedError, match="Insufficient funds"):
            await conn.create_order("BTC-USD", "buy", 1000)

    @patch("live_trading.exchange.coinbase.ccxt.coinbase")
    async def test_cancel_order(self, mock_coinbase_ctor, mock_ccxt_exchange):
        mock_coinbase_ctor.return_value = mock_ccxt_exchange
        conn = CoinbaseConnector({"api_key": "key", "secret": "secret"})
        await conn.connect()

        result = await conn.cancel_order("order-123", "BTC-USD")

        assert result is True

    @patch("live_trading.exchange.coinbase.ccxt.coinbase")
    async def test_get_order_status(self, mock_coinbase_ctor, mock_ccxt_exchange):
        mock_coinbase_ctor.return_value = mock_ccxt_exchange
        conn = CoinbaseConnector({"api_key": "key", "secret": "secret"})
        await conn.connect()

        order = await conn.get_order_status("coinbase-order-123", "BTC-USD")

        assert isinstance(order, ExchangeOrder)
        assert order.id == "coinbase-order-123"
        assert order.status == "closed"

    @patch("live_trading.exchange.coinbase.ccxt.coinbase")
    async def test_get_ticker(self, mock_coinbase_ctor, mock_ccxt_exchange):
        mock_coinbase_ctor.return_value = mock_ccxt_exchange
        conn = CoinbaseConnector({"api_key": "key", "secret": "secret"})
        await conn.connect()

        ticker = await conn.get_ticker("BTC-USD")

        assert ticker["symbol"] == "BTC-USD"
        assert ticker["price"] == 50000.0

    @patch("live_trading.exchange.coinbase.ccxt.coinbase")
    async def test_fetch_ohlcv(self, mock_coinbase_ctor, mock_ccxt_exchange):
        mock_coinbase_ctor.return_value = mock_ccxt_exchange
        conn = CoinbaseConnector({"api_key": "key", "secret": "secret"})
        await conn.connect()

        candles = await conn.fetch_ohlcv("BTC-USD")

        assert len(candles) == 1
        assert candles[0][4] == 50500.0

    def test_to_ccxt_symbol(self):
        conn = CoinbaseConnector({})
        assert conn._to_ccxt_symbol("BTC-USD") == "BTC/USD"
        assert conn._to_ccxt_symbol("ETH-USD") == "ETH/USD"
        assert conn._to_ccxt_symbol("ETH-USDC") == "ETH/USDC"
        assert conn._to_ccxt_symbol("SOL/USD") == "SOL/USD"
