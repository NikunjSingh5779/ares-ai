"""Exchange connector factory.

Usage::

    connector = create_exchange("binance", {"api_key": "...", "secret": "..."})
    await connector.connect()
    balance = await conn.get_balance()

Supported exchanges: binance, bybit, coinbase, kraken, zerodha, ibkr
"""

from __future__ import annotations

from typing import Any

from live_trading.exchange.base import ExchangeConnector


def create_exchange(name: str, config: dict[str, Any] | None = None) -> ExchangeConnector:
    """Create an exchange connector by name.

    Args:
        name: Exchange name (``"binance"``, ``"bybit"``, ``"coinbase"``,
              ``"kraken"``, ``"zerodha"``, ``"ibkr"``).
        config: Dict with keys like ``api_key``, ``secret``, ``testnet``, etc.

    Returns:
        An initialized (but not connected) ExchangeConnector.

    Raises:
        ValueError: If the exchange name is unknown.
    """
    config = config or {}

    if name == "binance":
        from live_trading.exchange.binance import BinanceConnector

        return BinanceConnector(config)

    if name == "bybit":
        from live_trading.exchange.bybit import BybitConnector

        return BybitConnector(config)

    if name == "coinbase":
        from live_trading.exchange.coinbase import CoinbaseConnector

        return CoinbaseConnector(config)

    if name == "kraken":
        from live_trading.exchange.kraken import KrakenConnector

        return KrakenConnector(config)

    if name == "zerodha":
        from live_trading.exchange.zerodha import ZerodhaStubConnector

        return ZerodhaStubConnector(config)

    if name == "ibkr":
        from live_trading.exchange.ibkr import IbkrStubConnector

        return IbkrStubConnector(config)

    msg = (
        f"Unknown exchange: {name}. "
        f"Supported: binance, bybit, coinbase, kraken, zerodha, ibkr"
    )
    raise ValueError(msg)
