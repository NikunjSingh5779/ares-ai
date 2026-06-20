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

import pytest

from agents.execution import ExecutionAgent, ExecutionInput
from backend.data.models import OHLCVData
from paper_trading.engine import PaperTradingEngine


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


def approved_risk_output() -> dict:
    """Return a risk output with trade approved."""
    return {
        "approved": True,
        "max_position_size": 1.5,
        "stop_loss": 48000.0,
        "risk_score": 35.0,
        "reasons": ["Within risk limits"],
        "rationale": "Trade approved",
    }


def rejected_risk_output() -> dict:
    """Return a risk output with trade rejected."""
    return {
        "approved": False,
        "max_position_size": None,
        "stop_loss": None,
        "risk_score": 85.0,
        "reasons": ["Risk score too high"],
        "rationale": "Trade rejected",
    }


def long_market_analyst() -> dict:
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
    async def test_output_structure(self) -> None:
        """Output dict should match ExecutionOutput schema fields."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=approved_risk_output(),
            )
        )
        # All ExecutionOutput fields should be present
        assert "executed" in result
        assert "order_id" in result
        assert "fill_price" in result
        assert "filled_quantity" in result
        assert "rationale" in result

    async def test_executed_true_on_approval(self) -> None:
        """executed=True when risk approved and direction is not flat."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=approved_risk_output(),
            )
        )
        assert result["executed"] is True
        assert result["order_id"] is not None
        assert result["fill_price"] == 50500.0  # latest candle close
        assert result["filled_quantity"] == 1.5  # from risk max_position_size
        assert "Executed" in result["rationale"]

    async def test_executed_false_no_risk_output(self) -> None:
        """executed=False when no risk output provided."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=None,
            )
        )
        assert result["executed"] is False
        assert "no risk output" in result["rationale"].lower()

    async def test_executed_false_risk_rejected(self) -> None:
        """executed=False when risk rejected the trade."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=rejected_risk_output(),
            )
        )
        assert result["executed"] is False
        assert "rejected" in result["rationale"].lower()

    async def test_executed_false_flat_direction(self) -> None:
        """executed=False when market analyst says flat."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine)

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
        assert result["executed"] is False
        assert "flat" in result["rationale"].lower()

    async def test_executed_false_no_market_analyst(self) -> None:
        """executed=False when no market analyst output."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=None,
                risk_output=approved_risk_output(),
            )
        )
        assert result["executed"] is False

    async def test_fill_price_from_latest_candle(self) -> None:
        """Fill price should be the close of the latest candle."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=default_candles(),
                market_analyst_output=long_market_analyst(),
                risk_output=approved_risk_output(),
            )
        )
        assert result["fill_price"] == 50500.0

    async def test_empty_candles(self) -> None:
        """executed=False when no candles provided."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine)

        result = await agent.process(
            ExecutionInput(
                symbol="BTC-USD",
                candles=[],
                market_analyst_output=long_market_analyst(),
                risk_output=approved_risk_output(),
            )
        )
        assert result["executed"] is False
        assert "no candle" in result["rationale"].lower()

    async def test_reversal_detected(self) -> None:
        """Reversal signal should be reflected in output."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine)

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
        assert result["executed"] is True
        assert "Executed" in result["rationale"]

    async def test_short_execution(self) -> None:
        """Short direction should execute correctly."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine)

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
        assert result["executed"] is True
        assert result["fill_price"] == 3000.0

    async def test_run_method(self) -> None:
        """The BaseAgent.run() wrapper should work end-to-end."""
        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine)

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
