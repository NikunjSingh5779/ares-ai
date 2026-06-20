"""Live trading engine with safety gates.

Exchange connectors, safety gates, order audit, and live trading engine
for the ARES AI platform.
"""

from __future__ import annotations

from live_trading.audit import AuditEntry, OrderAuditor
from live_trading.engine import LiveTradingEngine
from live_trading.exceptions import (
    ExchangeConnectionError,
    KillSwitchTrippedError,
    LiveTradingError,
    ModeError,
    OrderRejectedError,
    PromotionGateError,
)
from live_trading.exchange import create_exchange
from live_trading.exchange.base import ExchangeConnector
from live_trading.safety import KillSwitch, ModeManager, PromotionGate, TradingMode

__all__ = [
    "LiveTradingEngine",
    "ExchangeConnector",
    "create_exchange",
    "KillSwitch",
    "ModeManager",
    "PromotionGate",
    "TradingMode",
    "OrderAuditor",
    "AuditEntry",
    "LiveTradingError",
    "KillSwitchTrippedError",
    "PromotionGateError",
    "ExchangeConnectionError",
    "ModeError",
    "OrderRejectedError",
]
