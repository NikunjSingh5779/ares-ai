"""Exchange connector abstract base class.

Defines the interface all exchange connectors must implement.
Connectors wrap CCXT (or native APIs) behind a unified interface
so the LiveTradingEngine is exchange-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Data structures — exchange-agnostic
# ---------------------------------------------------------------------------


@dataclass
class ExchangeBalance:
    """Snapshot of account balances on an exchange."""

    total: dict[str, float] = field(default_factory=dict)
    free: dict[str, float] = field(default_factory=dict)
    used: dict[str, float] = field(default_factory=dict)


@dataclass
class ExchangeOrder:
    """A live order placed on an exchange."""

    id: str
    symbol: str
    side: Literal["buy", "sell"]
    type: str = "market"  # market, limit, stop, etc.
    quantity: float = 0.0
    price: float | None = None
    filled: float = 0.0
    remaining: float = 0.0
    status: str = "open"  # open, closed, canceled, failed
    timestamp: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExchangePosition:
    """An open position on an exchange (for perpetual/futures)."""

    symbol: str
    side: Literal["long", "short"]
    quantity: float
    entry_price: float
    unrealized_pnl: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract connector
# ---------------------------------------------------------------------------


class ExchangeConnector(ABC):
    """Abstract base for all exchange connectors.

    Every method that touches the exchange network must handle timeouts
    and connection errors internally and raise ExchangeConnectionError
    on unrecoverable failures.

    Implementations SHOULD:
    - Use CCXT for REST endpoints when possible.
    - Map CCXT exceptions to our exception hierarchy.
    - Log every API call with latency.
    """

    def __init__(self, exchange_name: str, config: dict[str, Any] | None = None) -> None:
        self.exchange_name = exchange_name
        self.config = config or {}

    # ── Lifecycle ──────────────────────────────────────────────────

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to the exchange and verify authentication.

        Returns:
            True if connected and authenticated successfully.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the exchange and clean up resources."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the connector is currently connected."""

    # ── Account ────────────────────────────────────────────────────

    @abstractmethod
    async def get_balance(self) -> ExchangeBalance:
        """Fetch the current account balance."""

    # ── Orders ─────────────────────────────────────────────────────

    @abstractmethod
    async def create_order(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> ExchangeOrder:
        """Place an order on the exchange.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            side: "buy" or "sell".
            quantity: Amount in base currency.
            order_type: "market", "limit", "stop", etc.
            price: Required for limit/stop orders.
            params: Exchange-specific parameters.

        Returns:
            ExchangeOrder with the exchange-assigned ID.

        Raises:
            ExchangeConnectionError: On network/API failure.
            OrderRejectedError: If the exchange rejects the order.
        """

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an open order.

        Returns:
            True if the order was successfully canceled.
        """

    @abstractmethod
    async def cancel_all_orders(self, symbol: str) -> bool:
        """Cancel all open orders for a specific symbol."""

    @abstractmethod
    async def get_order_status(self, order_id: str, symbol: str) -> ExchangeOrder:
        """Get the current status of an order."""

    # ── Market data ────────────────────────────────────────────────

    @abstractmethod
    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        """Get the current ticker for a symbol (latest price, volume, etc.)."""

    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> list[list[float]]:
        """Fetch OHLCV candles.

        Returns:
            List of candles, each as [timestamp, open, high, low, close, volume].
        """
