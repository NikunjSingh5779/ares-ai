"""Tests for the Execution Agent.

Tests cover:
- Output structure matches ExecutionOutput schema
- executed=True when risk approved and signal direction != flat
- executed=False when no risk output
- executed=False when risk rejected
- Fill price from latest candle close
- Empty candles handling
- Reversal detection via engine
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.execution import ExecutionAgent, ExecutionInput
from backend.data.models import OHLCVData
from live_trading.safety import TradingMode
from paper_trading.engine import PaperTradingEngine


@pytest.fixture
def mock_live_engine():
    engine = MagicMock()
    engine.mode = TradingMode.HUMAN_APPROVAL
    engine.paper_record = AsyncMock(return_value={"promotion": {"passed": False}})
    return engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_candle(
    close: float,
    high: float | None = None,
    low: float | None = None,
    open_: float | None = None,
    timestamp: datetime | None = None,
    symbol: str = "BTC-USD",
) -> OHLCVData:
    """Create a simple OHLCV candle for testing."""
    return OHLCVData(
        symbol=symbol,
        source="yahoo",
        interval="1d",
        timestamp=timestamp or datetime(2025, 1, 1),
        open=open_ or close,
        high=high or close,
        low=low or close,
        close=close,
        volume=1000.0,
    )


def default_candles() -> list[OHLCVData]:
    """Return a default candle list for testing."""
    return [
        make_candle(49000.0, timestamp=datetime(2025, 1, 1)),
        make_candle(50000.0, timestamp=datetime(2025, 1, 2)),
        make_candle(50500.0, timestamp=datetime(2025, 1, 3)),
    ]


def approved_risk_output() -> dict[str, Any]:
    """Return a risk output with trade approved."""
    return {
        "approved": True,
        "max_position_size": 1.5,
        "stop_loss": 48000.0,
        "risk_score": 35.0,
        "reasons": ["Within risk limits"],
        "rationale": "Trade approved",
    }


def rejected_risk_output() -> dict[str, Any]:
    """Return a risk output with trade rejected."""
    return {
        "approved": False,
        "max_position_size": None,
        "stop_loss": None,
        "risk_score": 85.0,
        "reasons": ["Risk score too high"],
        "rationale": "Trade rejected",
    }


def long_market_analyst() -> dict[str, Any]:
    """Return a market analyst output with long direction."""
    return {
        "confidence": 85.0,
        "direction": "long",
        "indicators": {"rsi_14": 45.2},
        "rationale": "Bullish trend detected",
        "strategy_name": "trend_follow",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExecutionAgent:
    async def test_output_structure(self, mock_live_engine) -> None:
        """Output dict should match ExecutionOutput schema fields."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=approved_risk_output(),
            )
        )
        # All ExecutionOutput fields should be present
        assert hasattr(result, "executed")
        assert hasattr(result, "order_id")
        assert hasattr(result, "fill_price")
        assert hasattr(result, "filled_quantity")
        assert hasattr(result, "rationale")

    async def test_executed_true_on_approval(self, mock_live_engine) -> None:
        """executed=True when risk approved and direction is not flat."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=approved_risk_output(),
            )
        )
        assert result.executed is True
        assert result.order_id is not None
        assert result.fill_price == 50500.0  # latest candle close
        assert result.filled_quantity in (1.5, None)  # from risk max_position_size
        assert "EXECUTED" in result.rationale.upper()

    async def test_reports_actual_slipped_fill_and_capped_quantity(self, mock_live_engine) -> None:
        """The agent must report/persist the engine's fill, not the signal."""
        engine = PaperTradingEngine(
            initial_capital=100000.0,
            commission_pct=0.001,
            slippage_pct=0.001,
        )
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)
        risk_output = approved_risk_output()
        risk_output["max_position_size"] = 100.0  # deliberately oversized

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=risk_output,
            )
        )

        expected_fill = 50500.0 * 1.001
        expected_quantity = 100000.0 / (expected_fill * 1.001)
        assert result.executed is True
        assert result.fill_price == pytest.approx(expected_fill)
        assert result.filled_quantity == pytest.approx(expected_quantity)
        assert len(engine._positions) == 1
        assert engine._positions[0].quantity == pytest.approx(expected_quantity)

    async def test_persists_actual_fill_and_quantity(self, mock_live_engine) -> None:
        """The DB position row must match the engine fill, not the request."""
        engine = PaperTradingEngine(
            initial_capital=100000.0,
            commission_pct=0.001,
            slippage_pct=0.001,
        )
        session = _FakeSession()
        agent = ExecutionAgent(
            engine=engine,
            live_engine=mock_live_engine,
            session_factory=_FakeSessionFactory(session),  # type: ignore[arg-type]
        )
        risk_output = approved_risk_output()
        risk_output["max_position_size"] = 100.0

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=risk_output,
            )
        )

        assert result.fill_price is not None
        assert result.filled_quantity is not None
        inserts = [params for sql, params in session.calls if "INSERT INTO positions" in sql]
        assert len(inserts) == 1
        assert inserts[0]["quantity"] == pytest.approx(result.filled_quantity)
        assert inserts[0]["entry_price"] == pytest.approx(result.fill_price)
        assert inserts[0]["market_value"] == pytest.approx(result.fill_price * result.filled_quantity)

    async def test_reversal_persists_buy_sell_side(self, mock_live_engine) -> None:
        """trade_history uses buy/sell, not the engine's long/short labels."""
        engine = PaperTradingEngine(initial_capital=100000.0)
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        session = _FakeSession()
        agent = ExecutionAgent(
            engine=engine,
            live_engine=mock_live_engine,
            session_factory=_FakeSessionFactory(session),  # type: ignore[arg-type]
        )

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output={
                    "confidence": 80.0,
                    "direction": "short",
                    "indicators": {},
                    "rationale": "Bearish reversal",
                },
                risk_output=approved_risk_output(),
            )
        )

        assert result.executed is True
        inserts = [params for sql, params in session.calls if "INSERT INTO trade_history" in sql]
        assert len(inserts) == 1
        assert inserts[0]["side"] == "buy"  # the closed long's entry side

    async def test_rejects_when_approved_but_no_position_size(self, mock_live_engine) -> None:
        """Regression guard: if the Risk Agent approves a trade but supplies
        no valid position size (e.g. price data was missing when it ran),
        the executor must reject the trade rather than silently defaulting
        to a hardcoded 1.0-unit quantity — which for an asset like BTC could
        be an enormous, un-sized order.
        """
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)

        risk_output = approved_risk_output()
        risk_output["max_position_size"] = None

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=risk_output,
            )
        )
        assert result.executed is False
        assert result.order_id is None
        assert "no valid position size" in result.rationale.lower()

    async def test_rejects_when_approved_but_zero_position_size(self, mock_live_engine) -> None:
        """Same as above, but for an explicit 0 rather than None."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)

        risk_output = approved_risk_output()
        risk_output["max_position_size"] = 0

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=risk_output,
            )
        )
        assert result.executed is False

    async def test_executed_false_no_risk_output(self, mock_live_engine) -> None:
        """executed=False when no risk output provided."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=None,
            )
        )
        assert result.executed is False
        assert "no risk output" in result.rationale.lower()

    async def test_executed_false_risk_rejected(self, mock_live_engine) -> None:
        """executed=False when risk rejected the trade."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=rejected_risk_output(),
            )
        )
        assert result.executed is False
        assert "rejected" in result.rationale.lower()

    async def test_executed_false_flat_direction(self, mock_live_engine) -> None:
        """executed=False when market analyst says flat."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output={
                    "confidence": 30.0,
                    "direction": "flat",
                    "indicators": {},
                    "rationale": "No clear signal",
                },
                risk_output=approved_risk_output(),
            )
        )
        assert result.executed is False
        assert "flat" in result.rationale.lower()

    async def test_executed_false_no_market_analyst(self, mock_live_engine) -> None:
        """executed=False when no market analyst output."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=None,
                risk_output=approved_risk_output(),
            )
        )
        assert result.executed is False

    async def test_fill_price_from_latest_candle(self, mock_live_engine) -> None:
        """Fill price should be the close of the latest candle."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=approved_risk_output(),
            )
        )
        assert result.fill_price == 50500.0

    async def test_empty_candles(self, mock_live_engine) -> None:
        """executed=False when no candles provided."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=[],
                market_analyst_output=long_market_analyst(),
                risk_output=approved_risk_output(),
            )
        )
        assert result.executed is False
        assert "no candle" in result.rationale.lower()

    async def test_reversal_detected(self, mock_live_engine) -> None:
        """Reversal signal should be reflected in output."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)

        # Open long first
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)

        # Now execute opposite direction via agent
        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output={
                    "confidence": 80.0,
                    "direction": "short",
                    "indicators": {},
                    "rationale": "Bearish reversal",
                },
                risk_output=approved_risk_output(),
            )
        )
        # Should have executed (reversal closes old, opens new)
        assert result.executed is True
        assert "EXECUTED" in result.rationale.upper()

    async def test_short_execution(self, mock_live_engine) -> None:
        """Short direction should execute correctly."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)

        result = await agent.process(
            ExecutionInput(
                symbol="ETH-USD",
                candles=[make_candle(3000.0)],
                market_analyst_output={
                    "confidence": 75.0,
                    "direction": "short",
                    "indicators": {},
                    "rationale": "Overbought",
                },
                risk_output=approved_risk_output(),
            )
        )
        assert result.executed is True
        assert result.fill_price == 3000.0

    async def test_run_method(self, mock_live_engine) -> None:
        """The BaseAgent.run() wrapper should work end-to-end."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine, live_engine=mock_live_engine)

        result = await agent.run(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=approved_risk_output(),
            )
        )
        assert result.executed is True  # FlexibleSchema -> Pydantic attribute access
        assert result.fill_price == 50500.0


class _FakeResult:
    def __init__(self, value: str = "fake-id") -> None:
        self._value = value

    def scalar(self) -> str:
        return self._value


class _FakeSession:
    """Captures parameterized SQL for assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.committed = False

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        self.calls.append((str(statement), params or {}))
        return _FakeResult()

    async def commit(self) -> None:
        self.committed = True


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> _FakeSessionContext:
        return _FakeSessionContext(self._session)
