"""Edge-case tests for LiveTradingEngine — drawdown, convenience wrappers, DB exception."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from live_trading import (
    ExchangeConnector,
    KillSwitch,
    LiveTradingEngine,
    ModeManager,
    PromotionGate,
    TradingMode,
)
from live_trading.exceptions import ExchangeConnectionError


@pytest.fixture
def mock_exchange():
    """Create a mock exchange connector."""
    exchange = AsyncMock(spec=ExchangeConnector)
    exchange.exchange_name = "mock_exchange"
    exchange.is_connected = True
    exchange.connect = AsyncMock(return_value=True)
    exchange.disconnect = AsyncMock()
    exchange.get_balance = AsyncMock(
        return_value=MagicMock(total={"BTC": 0.1, "USD": 50000.0})
    )
    exchange.cancel_order = AsyncMock(return_value=True)
    exchange.cancel_all_orders = AsyncMock()
    return exchange


@pytest.fixture
def engine(mock_exchange):
    """Create a LiveTradingEngine with mocked dependencies."""
    ks = KillSwitch(max_drawdown_pct=15.0)
    mm = ModeManager(TradingMode.SEMI)
    pg = PromotionGate(min_paper_trades=10, min_paper_days=5)
    eng = LiveTradingEngine(mock_exchange, ks, mm, pg)
    eng.set_paper_record(10, 5)
    return eng


class TestEngineEvaluateDrawdown:
    """evaluate_drawdown test coverage."""

    async def test_drawdown_below_threshold_does_not_trip(self, engine) -> None:
        await engine.start()
        result = await engine.evaluate_drawdown(10.0, "BTC/USDT")
        assert result is False
        assert not engine.kill_switch.is_active

    async def test_drawdown_above_threshold_trips_switch(self, engine, mock_exchange) -> None:
        await engine.start()
        result = await engine.evaluate_drawdown(20.0, "BTC/USDT")
        assert result is True
        assert engine.kill_switch.is_active
        assert engine.mode == TradingMode.HUMAN_APPROVAL
        mock_exchange.cancel_all_orders.assert_awaited_once_with("BTC/USDT")

    async def test_drawdown_trip_still_returns_true_when_cancel_fails(self, engine, mock_exchange) -> None:
        mock_exchange.cancel_all_orders = AsyncMock(side_effect=RuntimeError("Network error"))
        await engine.start()
        result = await engine.evaluate_drawdown(20.0, "BTC/USDT")
        assert result is True  # Should still report tripped even if cancel fails
        assert engine.kill_switch.is_active


class TestEngineConvenienceWrappers:
    """Convenience method edge cases."""

    async def test_get_balance_raises_when_disconnected(self, engine, mock_exchange) -> None:
        mock_exchange.is_connected = False
        with pytest.raises(ExchangeConnectionError, match="Exchange is not connected"):
            await engine.get_balance()

    async def test_get_balance_returns_total(self, engine, mock_exchange) -> None:
        await engine.start()
        balance = await engine.get_balance()
        assert isinstance(balance, dict)
        assert balance["BTC"] == 0.1

    async def test_get_open_orders_returns_empty(self, engine) -> None:
        orders = await engine.get_open_orders()
        assert orders == []

    async def test_cancel_order_raises_when_disconnected(self, engine, mock_exchange) -> None:
        mock_exchange.is_connected = False
        with pytest.raises(ExchangeConnectionError, match="Exchange is not connected"):
            await engine.cancel_order("order_1", "BTC/USDT")

    async def test_cancel_order_succeeds_when_connected(self, engine, mock_exchange) -> None:
        await engine.start()
        result = await engine.cancel_order("order_1", "BTC/USDT")
        assert result is True
        mock_exchange.cancel_order.assert_awaited_once_with("order_1", "BTC/USDT")


class TestEngineQueryPaperRecord:
    """_query_paper_record_from_db coverage."""

    async def test_db_backed_query_success(self, engine) -> None:
        """Verify the DB-backed path in _query_paper_record_from_db works."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 15

        mock_result_pnl = MagicMock()
        mock_result_pnl.scalar.return_value = 250.50

        mock_result_dd = MagicMock()
        mock_result_dd.scalar.return_value = 8.5

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            mock_result,    # trades count → 15
            mock_result,    # days count → 15
            mock_result_pnl,  # total_pnl → 250.50
            mock_result_dd,   # max_drawdown → 8.5
        ]
        mock_session.__aenter__.return_value = mock_session

        def factory():
            return mock_session

        engine._session_factory = factory
        engine.set_paper_record(5, 3)

        record = await engine._query_paper_record_from_db()
        assert record["trades"] == 15
        assert record["days"] == 15
        assert record["total_pnl"] == 250.50
        assert record["max_drawdown_pct"] == 8.5
        assert mock_session.execute.call_count == 4

    async def test_db_backed_query_missing_pnl_and_dd(self, engine) -> None:
        """When total_pnl/max_dd are None, they should be handled gracefully."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5

        mock_null = MagicMock()
        mock_null.scalar.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            mock_result,   # trades count → 5
            mock_result,   # days count → 5
            mock_null,     # total_pnl → None
            mock_null,     # max_drawdown → None
        ]
        mock_session.__aenter__.return_value = mock_session

        def factory():
            return mock_session

        engine._session_factory = factory
        record = await engine._query_paper_record_from_db()
        assert record["trades"] == 5
        assert record["days"] == 5
        assert record["total_pnl"] == 0.0
        assert record["max_drawdown_pct"] is None

    async def test_fallback_on_db_error(self, engine) -> None:
        """When the session factory raises an exception, fall back to in-memory."""
        engine.set_paper_record(5, 3)

        def failing_factory():
            raise RuntimeError("DB connection failed")

        engine._session_factory = failing_factory  # type: ignore[assignment]
        record = await engine._query_paper_record_from_db()
        assert record["trades"] == 5
        assert record["days"] == 3
        assert record["total_pnl"] is None
        assert record["max_drawdown_pct"] is None
