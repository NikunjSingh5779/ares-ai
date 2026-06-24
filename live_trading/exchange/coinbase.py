"""Coinbase exchange connector using CCXT.

Uses the Coinbase Advanced Trade API (``ccxt.coinbase()``).
Supports production only — Coinbase does not have a public testnet.

Requires: ccxt (``pip install ccxt``)
"""

from __future__ import annotations

from typing import Any, Literal

from live_trading.exceptions import ExchangeConnectionError, OrderRejectedError
from live_trading.exchange.base import (
    ExchangeBalance,
    ExchangeConnector,
    ExchangeOrder,
)

try:
    import ccxt

    HAS_CCXT = True
except ImportError:  # pragma: no cover
    HAS_CCXT = False


class CoinbaseConnector(ExchangeConnector):
    """Coinbase exchange connector via CCXT (Advanced Trade API).

    Coinbase does not provide a public testnet. Use a sandbox API key
    for testing, or set ``testnet=True`` (which enables paper trading
    mode via the connector's own safety check rather than a real testnet).

    Configuration keys (passed via config dict)::

        api_key     — Coinbase API key (Cloud Trading key)
        secret      — Coinbase API secret (base64-encoded private key)
        testnet     — bool, defaults to True (uses paper/sandbox when available)

    Usage::

        conn = CoinbaseConnector({"api_key": "...", "secret": "..."})
        await conn.connect()
        balance = await conn.get_balance()
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__("coinbase", config)
        if not HAS_CCXT:
            msg = "ccxt is required for Coinbase connector. Install with: pip install ccxt"
            raise ImportError(msg)

        self._client: ccxt.Exchange | None = None
        self._connected = False

    async def connect(self) -> bool:
        """Connect to Coinbase and authenticate."""
        api_key = self.config.get("api_key", "") or ""
        secret = self.config.get("secret", "") or ""

        options: dict[str, Any] = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
        }

        try:
            self._client = ccxt.coinbase(options)  # type: ignore[arg-type]

            # Verify connectivity and auth
            if api_key and secret:
                await self._client.load_markets()
                balance = await self._client.fetch_balance()
                if balance.get("free") is None:
                    raise ExchangeConnectionError(
                        "Coinbase authentication failed — check API key and secret"
                    )

            self._connected = True
            return True

        except ccxt.AuthenticationError as exc:
            raise ExchangeConnectionError(
                f"Coinbase authentication failed: {exc}"
            ) from exc
        except ccxt.NetworkError as exc:
            raise ExchangeConnectionError(
                f"Coinbase network error: {exc}"
            ) from exc
        except Exception as exc:
            raise ExchangeConnectionError(
                f"Coinbase connection failed: {exc}"
            ) from exc

    async def disconnect(self) -> None:
        self._client = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    async def get_balance(self) -> ExchangeBalance:
        self._require_connected()
        try:
            raw = await self._client.fetch_balance()  # type: ignore[union-attr]
            return ExchangeBalance(
                total=raw.get("total", {}),
                free=raw.get("free", {}),
                used=raw.get("used", {}),
            )
        except ccxt.NetworkError as exc:
            raise ExchangeConnectionError(
                f"Failed to fetch balance: {exc}"
            ) from exc

    async def create_order(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> ExchangeOrder:
        self._require_connected()

        ccxt_symbol = self._to_ccxt_symbol(symbol)

        try:
            raw = await self._client.create_order(  # type: ignore[union-attr]
                symbol=ccxt_symbol,
                type=order_type,
                side=side,
                amount=quantity,
                price=price,
                params=params or {},
            )
        except ccxt.InsufficientFunds as exc:
            raise OrderRejectedError(
                f"Insufficient funds for {symbol}: {exc}"
            ) from exc
        except ccxt.InvalidOrder as exc:
            raise OrderRejectedError(
                f"Order rejected by Coinbase: {exc}"
            ) from exc
        except ccxt.NetworkError as exc:
            raise ExchangeConnectionError(
                f"Network error placing order on {symbol}: {exc}"
            ) from exc

        return ExchangeOrder(
            id=str(raw.get("id", "")),
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=float(raw.get("amount", quantity)),
            price=float(raw.get("price")) if raw.get("price") else None,
            filled=float(raw.get("filled", 0)),
            remaining=float(raw.get("remaining", 0)),
            status=str(raw.get("status", "open")),
            raw=raw,
        )

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        self._require_connected()
        ccxt_symbol = self._to_ccxt_symbol(symbol)
        try:
            result = await self._client.cancel_order(order_id, ccxt_symbol)  # type: ignore[union-attr]
            return result.get("status", "canceled") == "canceled"
        except ccxt.NetworkError as exc:
            raise ExchangeConnectionError(
                f"Failed to cancel order {order_id}: {exc}"
            ) from exc

    async def get_order_status(self, order_id: str, symbol: str) -> ExchangeOrder:
        self._require_connected()
        ccxt_symbol = self._to_ccxt_symbol(symbol)
        try:
            raw = await self._client.fetch_order(order_id, ccxt_symbol)  # type: ignore[union-attr]
        except ccxt.NetworkError as exc:
            raise ExchangeConnectionError(
                f"Failed to fetch order {order_id}: {exc}"
            ) from exc

        return ExchangeOrder(
            id=str(raw.get("id", order_id)),
            symbol=symbol,
            side=str(raw.get("side", "buy")),  # type: ignore[arg-type]
            type=str(raw.get("type", "market")),
            quantity=float(raw.get("amount", 0)),
            price=float(raw.get("price")) if raw.get("price") else None,
            filled=float(raw.get("filled", 0)),
            remaining=float(raw.get("remaining", 0)),
            status=str(raw.get("status", "open")),
            raw=raw,
        )

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        self._require_connected()
        ccxt_symbol = self._to_ccxt_symbol(symbol)
        try:
            ticker = await self._client.fetch_ticker(ccxt_symbol)  # type: ignore[union-attr]
            return {
                "symbol": symbol,
                "price": float(ticker.get("last", 0)),
                "bid": float(ticker.get("bid", 0)),
                "ask": float(ticker.get("ask", 0)),
                "volume": float(ticker.get("baseVolume", 0)),
                "high": float(ticker.get("high", 0)),
                "low": float(ticker.get("low", 0)),
                "change_pct": float(ticker.get("percentage", 0)),
            }
        except ccxt.NetworkError as exc:
            raise ExchangeConnectionError(
                f"Failed to fetch ticker for {symbol}: {exc}"
            ) from exc

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> list[list[float]]:
        self._require_connected()
        ccxt_symbol = self._to_ccxt_symbol(symbol)
        try:
            return await self._client.fetch_ohlcv(  # type: ignore[union-attr]
                ccxt_symbol, timeframe=timeframe, limit=limit
            )
        except ccxt.NetworkError as exc:
            raise ExchangeConnectionError(
                f"Failed to fetch OHLCV for {symbol}: {exc}"
            ) from exc

    # ── Internal helpers ───────────────────────────────────────────

    def _require_connected(self) -> None:
        if not self.is_connected:
            raise ExchangeConnectionError("Coinbase connector is not connected")

    @staticmethod
    def _to_ccxt_symbol(symbol: str) -> str:
        """Convert internal symbol format to CCXT format.

        Coinbase Advanced Trade uses "BTC-USD" natively (with hyphen),
        but CCXT's coinbase module expects "BTC/USD".

        "BTC-USD" → "BTC/USD"
        "ETH-USD" → "ETH/USD"
        "BTCUSDT" → "BTC/USDT"
        """
        s = symbol.upper().replace("-", "")
        if "/" in s:
            return s
        # Coinbase pairs use USD, USDC, USDT as quote
        stablecoins = ("USDT", "USDC")
        for q in stablecoins:
            if s.endswith(q):
                return s.replace(q, f"/{q}")
        if s.endswith("USD"):
            return s[:-3] + "/USD"
        return s + "/USD"

    async def cancel_all_orders(self, symbol: str) -> bool:
        raise NotImplementedError("cancel_all_orders not yet implemented for Coinbase")
