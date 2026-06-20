"""Tests for the ExchangeConnector ABC contract.

Verifies that the ABC enforces its interface properly and that stubs
implement it correctly.
"""

from __future__ import annotations

import pytest

from live_trading.exchange.base import (
    ExchangeBalance,
    ExchangeConnector,
    ExchangeOrder,
    ExchangePosition,
)


def test_exchange_balance_defaults() -> None:
    b = ExchangeBalance()
    assert b.total == {}
    assert b.free == {}
    assert b.used == {}


def test_exchange_order_required_fields() -> None:
    o = ExchangeOrder(id="123", symbol="BTC/USDT", side="buy")
    assert o.id == "123"
    assert o.symbol == "BTC/USDT"
    assert o.side == "buy"
    assert o.type == "market"
    assert o.quantity == 0.0
    assert o.price is None
    assert o.filled == 0.0
    assert o.remaining == 0.0
    assert o.status == "open"


def test_exchange_position_fields() -> None:
    p = ExchangePosition(symbol="BTC/USDT", side="long", quantity=1.0, entry_price=50000.0)
    assert p.symbol == "BTC/USDT"
    assert p.side == "long"
    assert p.quantity == 1.0
    assert p.entry_price == 50000.0
    assert p.unrealized_pnl == 0.0


def test_abc_cannot_instantiate() -> None:
    """ExchangeConnector is abstract and cannot be instantiated directly."""
    with pytest.raises(TypeError):
        ExchangeConnector("test")  # type: ignore[abstract]


def test_stub_connectors_implement_abc() -> None:
    """All stub connectors should be concrete (instantiable) subclasses."""
    from live_trading.exchange.bybit import BybitConnector
    from live_trading.exchange.zerodha import ZerodhaStubConnector
    from live_trading.exchange.ibkr import IbkrStubConnector

    for cls in [BybitConnector, ZerodhaStubConnector, IbkrStubConnector]:
        instance = cls({})
        assert isinstance(instance, ExchangeConnector)
        assert instance.exchange_name is not None
        assert isinstance(instance.config, dict)
