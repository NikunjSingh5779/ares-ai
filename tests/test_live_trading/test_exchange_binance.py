"""Tests for the Binance CCXT connector (mocked CCXT).

All CCXT calls are mocked to avoid network dependencies.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import ccxt
import pytest

from live_trading.exceptions import ExchangeConnectionError, OrderRejectedError
from live_trading.exchange.binance import BinanceConnector


# Ensure CCXT is "available" even if not installed in the test env
@pytest.fixture(autouse=True)
def _mock_ccxt_import():
    """Mock ccxt HAS_CCXT flag so BinanceConnector can be imported."""
    with patch("live_trading.exchange.binance.HAS_CCXT", True):
        yield


@pytest.fixture
def mock_ccxt_exchange():
    """Create a mock ccxt exchange instance."""
    mock_exchange = MagicMock()
    mock_exchange.load_markets = AsyncMock()
    mock_exchange.fetch_balance = AsyncMock(
        return_value={
            "free": {"USDT": 1000.0},
            "total": {"USDT": 1000.0},
            "used": {"USDT": 0.0},
        }
    )
    mock_exchange.create_order = AsyncMock(
        return_value={
            "id": "binance_order_123",
            "amount": 0.01,
            "price": 50000.0,
            "filled": 0.01,
            "remaining": 0.0,
            "status": "closed",
        }
    )
    mock_exchange.cancel_order = AsyncMock(return_value={"status": "canceled"})
    mock_exchange.fetch_order = AsyncMock(
        return_value={
            "id": "binance_order_123",
            "side": "buy",
            "type": "limit",
            "amount": 0.01,
            "price": 50000.0,
            "filled": 0.005,
            "remaining": 0.005,
            "status": "open",
        }
    )
    mock_exchange.fetch_ticker = AsyncMock(
        return_value={
            "last": 50000.0,
            "bid": 49900.0,
            "ask": 50100.0,
            "baseVolume": 10000.0,
            "high": 51000.0,
            "low": 49000.0,
            "percentage": 2.5,
        }
    )
    mock_exchange.fetch_ohlcv = AsyncMock(
        return_value=[
            [1609459200000, 29000.0, 29500.0, 28800.0, 29200.0, 1000.0],
            [1609545600000, 29200.0, 29800.0, 29100.0, 29600.0, 1200.0],
        ]
    )
    return mock_exchange


@pytest.fixture
def connector():
    """Create a BinanceConnector with test config."""
    return BinanceConnector({"api_key": "test_key", "secret": "test_secret", "testnet": True})


class TestBinanceConnectorInit:
    """BinanceConnector initialization tests."""

    def test_init_stores_config(self) -> None:
        conn = BinanceConnector({"api_key": "abc", "secret": "xyz"})
        assert conn.exchange_name == "binance"
        assert conn.config["api_key"] == "abc"

    def test_init_not_connected(self) -> None:
        conn = BinanceConnector()
        assert not conn.is_connected


class TestBinanceConnectorConnect:
    """Connection tests with mocked CCXT."""

    @patch("live_trading.exchange.binance.ccxt")
    async def test_connect_success(self, mock_ccxt_module, mock_ccxt_exchange) -> None:
        mock_ccxt_module.binance.return_value = mock_ccxt_exchange
        conn = BinanceConnector({"api_key": "key", "secret": "secret", "testnet": True})
        result = await conn.connect()
        assert result is True
        assert conn.is_connected

    @patch("live_trading.exchange.binance.ccxt")
    async def test_connect_sets_testnet_urls(self, mock_ccxt_module, mock_ccxt_exchange) -> None:
        mock_ccxt_module.binance.return_value = mock_ccxt_exchange
        conn = BinanceConnector({"api_key": "key", "secret": "secret", "testnet": True})
        await conn.connect()
        mock_ccxt_exchange.set_sandbox_mode.assert_called_once_with(True)

    @patch("live_trading.exchange.binance.ccxt")
    async def test_connect_no_auth_skips_balance_check(
        self, mock_ccxt_module, mock_ccxt_exchange
    ) -> None:
        mock_ccxt_module.binance.return_value = mock_ccxt_exchange
        conn = BinanceConnector({"testnet": True})
        result = await conn.connect()
        assert result is True
        mock_ccxt_exchange.load_markets.assert_not_called()
        mock_ccxt_exchange.fetch_balance.assert_not_called()


class TestBinanceConnectorBalance:
    """Balance fetching tests."""

    @patch("live_trading.exchange.binance.ccxt")
    async def test_get_balance(self, mock_ccxt_module, mock_ccxt_exchange) -> None:
        mock_ccxt_module.binance.return_value = mock_ccxt_exchange
        conn = BinanceConnector({"api_key": "key", "secret": "secret", "testnet": True})
        await conn.connect()

        balance = await conn.get_balance()
        assert "USDT" in balance.total
        assert balance.total["USDT"] == 1000.0


class TestBinanceConnectorOrders:
    """Order placement and management tests."""

    @patch("live_trading.exchange.binance.ccxt")
    async def test_create_order(self, mock_ccxt_module, mock_ccxt_exchange) -> None:
        mock_ccxt_module.binance.return_value = mock_ccxt_exchange
        conn = BinanceConnector({"api_key": "key", "secret": "secret", "testnet": True})
        await conn.connect()

        order = await conn.create_order("BTC-USD", "buy", 0.01)
        assert order.id == "binance_order_123"
        assert order.symbol == "BTC-USD"
        assert order.side == "buy"

    @patch("live_trading.exchange.binance.ccxt")
    async def test_cancel_order(self, mock_ccxt_module, mock_ccxt_exchange) -> None:
        mock_ccxt_module.binance.return_value = mock_ccxt_exchange
        conn = BinanceConnector({"api_key": "key", "secret": "secret", "testnet": True})
        await conn.connect()

        result = await conn.cancel_order("order_123", "BTC-USD")
        assert result is True

    @patch("live_trading.exchange.binance.ccxt")
    async def test_get_order_status(self, mock_ccxt_module, mock_ccxt_exchange) -> None:
        mock_ccxt_module.binance.return_value = mock_ccxt_exchange
        conn = BinanceConnector({"api_key": "key", "secret": "secret", "testnet": True})
        await conn.connect()

        order = await conn.get_order_status("binance_order_123", "BTC-USD")
        assert order.id == "binance_order_123"
        assert order.side == "buy"
        assert order.status == "open"


class TestBinanceConnectorMarketData:
    """Market data tests."""

    @patch("live_trading.exchange.binance.ccxt")
    async def test_get_ticker(self, mock_ccxt_module, mock_ccxt_exchange) -> None:
        mock_ccxt_module.binance.return_value = mock_ccxt_exchange
        conn = BinanceConnector({"api_key": "key", "secret": "secret", "testnet": True})
        await conn.connect()

        ticker = await conn.get_ticker("BTC-USD")
        assert ticker["symbol"] == "BTC-USD"
        assert ticker["price"] == 50000.0
        assert ticker["bid"] == 49900.0
        assert ticker["ask"] == 50100.0

    @patch("live_trading.exchange.binance.ccxt")
    async def test_fetch_ohlcv(self, mock_ccxt_module, mock_ccxt_exchange) -> None:
        mock_ccxt_module.binance.return_value = mock_ccxt_exchange
        conn = BinanceConnector({"api_key": "key", "secret": "secret", "testnet": True})
        await conn.connect()

        candles = await conn.fetch_ohlcv("BTC-USD", timeframe="1d", limit=2)
        assert len(candles) == 2
        assert len(candles[0]) == 6


class TestBinanceConnectorErrors:
    """Error handling tests.

    We patch `ccxt.binance` (the constructor) rather than the whole
    ccxt module so real ccxt exception classes remain available for
    ``side_effect`` and ``pytest.raises``.
    """

    @patch("live_trading.exchange.binance.ccxt.binance")
    async def test_create_order_network_error(self, mock_binance_ctor) -> None:
        exchange = MagicMock()
        exchange.load_markets = AsyncMock()
        exchange.fetch_balance = AsyncMock(
            return_value={"free": {"USDT": 1000.0}, "total": {}, "used": {}}
        )
        exchange.create_order = AsyncMock(side_effect=ccxt.NetworkError("timeout"))
        mock_binance_ctor.return_value = exchange

        conn = BinanceConnector({"api_key": "key", "secret": "secret", "testnet": True})
        await conn.connect()

        result = await conn.create_order("BTC-USD", "buy", 0.01)
        assert result.status == "failed"
        assert result.raw is not None and "error" in result.raw

    @patch("live_trading.exchange.binance.ccxt.binance")
    async def test_create_order_insufficient_funds(self, mock_binance_ctor) -> None:
        exchange = MagicMock()
        exchange.load_markets = AsyncMock()
        exchange.fetch_balance = AsyncMock(
            return_value={"free": {"USDT": 1000.0}, "total": {}, "used": {}}
        )
        exchange.create_order = AsyncMock(side_effect=ccxt.InsufficientFunds("balance low"))
        mock_binance_ctor.return_value = exchange

        conn = BinanceConnector({"api_key": "key", "secret": "secret", "testnet": True})
        await conn.connect()

        result = await conn.create_order("BTC-USD", "buy", 1000.0)
        assert result.status == "failed"
        assert result.raw is not None and "error" in result.raw

    @patch("live_trading.exchange.binance.ccxt.binance")
    async def test_operation_when_not_connected(self, mock_binance_ctor) -> None:
        conn = BinanceConnector({"api_key": "key", "secret": "secret", "testnet": True})
        with pytest.raises(ExchangeConnectionError):
            await conn.get_balance()


class TestSymbolConversion:
    """Symbol format conversion tests."""

    @pytest.fixture
    def conn(self) -> BinanceConnector:
        with patch("live_trading.exchange.binance.HAS_CCXT", True):
            return BinanceConnector()

    def test_dash_usd_to_ccxt(self, conn: BinanceConnector) -> None:
        assert conn._to_ccxt_symbol("BTC-USD") == "BTC/USDT"

    def test_dash_eth_to_ccxt(self, conn: BinanceConnector) -> None:
        assert conn._to_ccxt_symbol("ETH-USD") == "ETH/USDT"

    def test_usdt_no_dash(self, conn: BinanceConnector) -> None:
        assert conn._to_ccxt_symbol("BTCUSDT") == "BTC/USDT"

    def test_already_slashed(self, conn: BinanceConnector) -> None:
        assert conn._to_ccxt_symbol("BTC/USDT") == "BTC/USDT"

    def test_lowercase(self, conn: BinanceConnector) -> None:
        assert conn._to_ccxt_symbol("btc-usd") == "BTC/USDT"

    def test_slash_without_usdt(self, conn: BinanceConnector) -> None:
        assert conn._to_ccxt_symbol("BTC/USD") == "BTC/USDT"

    def test_raw_base(self, conn: BinanceConnector) -> None:
        assert conn._to_ccxt_symbol("BTC") == "BTC/USDT"

    def test_eth_raw(self, conn: BinanceConnector) -> None:
        assert conn._to_ccxt_symbol("ETH") == "ETH/USDT"
