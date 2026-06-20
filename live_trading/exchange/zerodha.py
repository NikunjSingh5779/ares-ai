"""Zerodha stub connector — same pattern as Bybit stub."""

from __future__ import annotations

from typing import Any, Literal

from live_trading.exchange.base import (
    ExchangeBalance,
    ExchangeConnector,
    ExchangeOrder,
)


class ZerodhaStubConnector(ExchangeConnector):
    """Stub Zerodha connector. Order methods raise NotImplementedError."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__("zerodha", config)
        self._connected = False

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get_balance(self) -> ExchangeBalance:
        return ExchangeBalance()

    async def create_order(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> ExchangeOrder:
        msg = "Zerodha connector is a stub — real order placement not yet implemented"
        raise NotImplementedError(msg)

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        msg = "Zerodha connector is a stub"
        raise NotImplementedError(msg)

    async def get_order_status(self, order_id: str, symbol: str) -> ExchangeOrder:
        msg = "Zerodha connector is a stub"
        raise NotImplementedError(msg)

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "price": 0.0, "volume": 0.0}

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> list[list[float]]:
        return []
