"""Tests for the Paper Trading Engine.

Tests cover:
- Initial state and configuration
- Opening long and short positions
- Closing positions with PnL calculation
- Stop-loss and take-profit triggers for long and short
- Reversal signals (opposite direction)
- Same-direction signals ignored
- Portfolio summary metrics
- Reset functionality
- Multiple positions across different symbols
"""

from __future__ import annotations

import pytest

from paper_trading.engine import PaperTradingEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> PaperTradingEngine:
    """PaperTradingEngine with default 100k initial capital."""
    return PaperTradingEngine(initial_capital=100000.0)


@pytest.fixture
def expensive_asset_engine() -> PaperTradingEngine:
    """Engine with enough capital to buy expensive assets."""
    return PaperTradingEngine(initial_capital=1_000_000.0)


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_default_initial_capital(self) -> None:
        engine = PaperTradingEngine()
        summary = engine.get_summary()
        assert summary.initial_capital == 100000.0
        assert summary.cash == 100000.0
        assert summary.total_trades == 0
        assert summary.open_positions == 0
        assert summary.total_pnl == 0.0

    def test_custom_initial_capital(self) -> None:
        engine = PaperTradingEngine(initial_capital=50000.0)
        summary = engine.get_summary()
        assert summary.initial_capital == 50000.0
        assert summary.cash == 50000.0

    def test_min_capital_floor(self) -> None:
        engine = PaperTradingEngine(initial_capital=100.0)
        assert engine._initial_capital == 1000.0  # clamped
        assert engine._cash == 1000.0

    def test_negative_initial_capital(self) -> None:
        engine = PaperTradingEngine(initial_capital=-5000.0)
        assert engine._initial_capital == 1000.0  # clamped
        assert engine._cash == 1000.0


# ---------------------------------------------------------------------------
# Opening positions
# ---------------------------------------------------------------------------


class TestOpenPositions:
    def test_open_long(self, engine: PaperTradingEngine) -> None:
        result = engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        assert result["accepted"] is True
        assert result["position_id"] is not None
        assert result["reversal"] is False
        assert result["reason"] == "ok"

        summary = engine.get_summary()
        assert summary.open_positions == 1
        # 1 BTC at $50k should cost $50k
        assert summary.cash == pytest.approx(50000.0)

    def test_open_short(self, engine: PaperTradingEngine) -> None:
        result = engine.execute_signal("ETH-USD", "short", 10.0, 3000.0)
        assert result["accepted"] is True
        assert result["position_id"] is not None

        summary = engine.get_summary()
        assert summary.open_positions == 1
        # 10 ETH at $3k should cost $30k
        assert summary.cash == pytest.approx(70000.0)

    def test_quantity_scaled_to_cash(self, engine: PaperTradingEngine) -> None:
        """Requesting more than available cash should scale down."""
        result = engine.execute_signal("BTC-USD", "long", 10.0, 50000.0)
        assert result["accepted"] is True
        summary = engine.get_summary()
        # Should only spend available cash (100k)
        assert summary.cash == pytest.approx(0.0)
        # Should own ~2 BTC (100k / 50k)
        assert len(engine._positions) == 1
        assert engine._positions[0].quantity == pytest.approx(2.0)

    def test_zero_quantity_rejected(self, engine: PaperTradingEngine) -> None:
        result = engine.execute_signal("BTC-USD", "long", 0.0, 50000.0)
        assert result["accepted"] is False
        assert "Quantity" in result["reason"]

    def test_negative_quantity_rejected(self, engine: PaperTradingEngine) -> None:
        result = engine.execute_signal("BTC-USD", "long", -1.0, 50000.0)
        assert result["accepted"] is False


# ---------------------------------------------------------------------------
# Closing positions
# ---------------------------------------------------------------------------


class TestClosePositions:
    def test_close_long_with_profit(self, engine: PaperTradingEngine) -> None:
        result = engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        pos_id = result["position_id"]

        # Close at $55k = $5k profit
        trade = engine.close_position(pos_id, 55000.0)
        assert trade is not None
        assert trade.pnl == pytest.approx(5000.0)
        assert trade.pnl_pct == pytest.approx(10.0)
        assert trade.exit_reason == "signal"

        summary = engine.get_summary()
        assert summary.open_positions == 0
        assert summary.total_trades == 1
        assert summary.total_pnl == pytest.approx(5000.0)

    def test_close_long_with_loss(self, engine: PaperTradingEngine) -> None:
        result = engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        pos_id = result["position_id"]

        trade = engine.close_position(pos_id, 45000.0)
        assert trade is not None
        assert trade.pnl == pytest.approx(-5000.0)
        assert trade.pnl_pct == pytest.approx(-10.0)

    def test_close_short_with_profit(self, engine: PaperTradingEngine) -> None:
        result = engine.execute_signal("ETH-USD", "short", 10.0, 3000.0)
        pos_id = result["position_id"]

        # Close at $2,700 = $3,000 profit (10 * 300)
        trade = engine.close_position(pos_id, 2700.0)
        assert trade is not None
        assert trade.pnl == pytest.approx(3000.0)

    def test_close_short_with_loss(self, engine: PaperTradingEngine) -> None:
        result = engine.execute_signal("ETH-USD", "short", 10.0, 3000.0)
        pos_id = result["position_id"]

        # Close at $3,300 = $3,000 loss
        trade = engine.close_position(pos_id, 3300.0)
        assert trade is not None
        assert trade.pnl == pytest.approx(-3000.0)

    def test_close_nonexistent_position(self, engine: PaperTradingEngine) -> None:
        trade = engine.close_position("nonexistent-id", 50000.0)
        assert trade is None

    def test_close_with_exit_reason(self, engine: PaperTradingEngine) -> None:
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        pos_id = engine._positions[0].id
        trade = engine.close_position(pos_id, 55000.0, exit_reason="take_profit")
        assert trade is not None
        assert trade.exit_reason == "take_profit"


# ---------------------------------------------------------------------------
# Stop-loss / Take-profit
# ---------------------------------------------------------------------------


class TestStopLossTakeProfit:
    def test_stop_loss_hit_long(self, engine: PaperTradingEngine) -> None:
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0, stop_loss=48000.0)
        # Candle low triggers stop loss
        closed = engine.check_sl_tp(high=50500.0, low=47500.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == "stop_loss"
        assert closed[0].pnl == pytest.approx(-2000.0)  # (48000 - 50000) * 1

    def test_take_profit_hit_long(self, engine: PaperTradingEngine) -> None:
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0, take_profit=55000.0)
        # Candle high triggers take profit
        closed = engine.check_sl_tp(high=56000.0, low=51000.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == "take_profit"
        assert closed[0].pnl == pytest.approx(5000.0)

    def test_stop_loss_hit_short(self, engine: PaperTradingEngine) -> None:
        engine.execute_signal("ETH-USD", "short", 10.0, 3000.0, stop_loss=3200.0)
        # Candle high triggers stop loss for short
        closed = engine.check_sl_tp(high=3300.0, low=2900.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == "stop_loss"

    def test_take_profit_hit_short(self, engine: PaperTradingEngine) -> None:
        engine.execute_signal("ETH-USD", "short", 10.0, 3000.0, take_profit=2700.0)
        # Candle low triggers take profit for short
        closed = engine.check_sl_tp(high=2950.0, low=2600.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == "take_profit"

    def test_sl_tp_not_hit(self, engine: PaperTradingEngine) -> None:
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0, stop_loss=48000.0, take_profit=55000.0)
        # Candle stays within range
        closed = engine.check_sl_tp(high=52000.0, low=49000.0)
        assert len(closed) == 0

    def test_sl_and_tp_both_reached_long_tp_checked_first(self, engine: PaperTradingEngine) -> None:
        """For long, take_profit is checked before stop_loss."""
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0, stop_loss=49000.0, take_profit=51000.0)
        # Both TP and SL levels breached
        closed = engine.check_sl_tp(high=51500.0, low=48500.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == "take_profit"  # TP checked first

    def test_sl_and_tp_both_reached_short_tp_checked_first(self, engine: PaperTradingEngine) -> None:
        """For short, take_profit is checked before stop_loss."""
        engine.execute_signal("ETH-USD", "short", 10.0, 3000.0, stop_loss=3100.0, take_profit=2900.0)
        closed = engine.check_sl_tp(high=3150.0, low=2850.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == "take_profit"


# ---------------------------------------------------------------------------
# Reversal signals
# ---------------------------------------------------------------------------


class TestReversals:
    def test_opposite_signal_reverses(self, engine: PaperTradingEngine) -> None:
        """Opposite direction closes existing and opens new."""
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        result = engine.execute_signal("BTC-USD", "short", 1.0, 55000.0)
        assert result["accepted"] is True
        assert result["reversal"] is True
        assert result["closed_trade"] is not None
        assert result["closed_trade"]["pnl"] == 5000.0  # 55k - 50k profit on long

        summary = engine.get_summary()
        assert summary.open_positions == 1  # New short position open
        assert summary.total_trades == 1  # Only the closed long counts

    def test_same_direction_ignored(self, engine: PaperTradingEngine) -> None:
        """Same direction while position open is ignored."""
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        result = engine.execute_signal("BTC-USD", "long", 0.5, 52000.0)
        assert result["accepted"] is False
        assert "Already in" in result["reason"]

        summary = engine.get_summary()
        assert summary.open_positions == 1  # Still just the original


# ---------------------------------------------------------------------------
# Portfolio summary
# ---------------------------------------------------------------------------


class TestPortfolioSummary:
    def test_summary_after_profitable_trades(self, engine: PaperTradingEngine) -> None:
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        pos_id = engine._positions[0].id
        engine.close_position(pos_id, 55000.0)

        engine.execute_signal("ETH-USD", "short", 10.0, 3000.0)
        pos_id2 = engine._positions[0].id
        engine.close_position(pos_id2, 2700.0)

        summary = engine.get_summary()
        assert summary.total_trades == 2
        assert summary.winning_trades == 2
        assert summary.losing_trades == 0
        assert summary.win_rate == 100.0
        assert summary.total_pnl == pytest.approx(8000.0)  # 5000 + 3000

    def test_summary_with_mixed_results(self, engine: PaperTradingEngine) -> None:
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        engine.close_position(engine._positions[0].id, 55000.0)  # +5000

        engine.execute_signal("BTC-USD", "long", 1.0, 60000.0)
        engine.close_position(engine._positions[0].id, 55000.0)  # -5000

        summary = engine.get_summary()
        assert summary.total_trades == 2
        assert summary.winning_trades == 1
        assert summary.losing_trades == 1
        assert summary.win_rate == 50.0
        assert summary.total_pnl == pytest.approx(0.0)

    def test_summary_total_return_pct(self, engine: PaperTradingEngine) -> None:
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        engine.close_position(engine._positions[0].id, 55000.0)

        summary = engine.get_summary()
        # 100k initial, now 100k + 5k profit = 105k
        # return = (105/100 - 1) * 100 = 5%
        assert summary.total_return_pct == pytest.approx(5.0)

    def test_summary_drawdown(self, engine: PaperTradingEngine) -> None:
        """Sequence of trades to produce a drawdown."""
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        engine.close_position(engine._positions[0].id, 55000.0)  # peak: 105k

        engine.execute_signal("BTC-USD", "long", 1.0, 60000.0)
        engine.close_position(engine._positions[0].id, 30000.0)  # big loss

        summary = engine.get_summary()
        # 100k → 105k → 45k after loss
        # Drawdown from peak 105k to 45k = 60/105 ≈ 57.14%
        assert summary.max_drawdown_pct > 0


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_state(self, engine: PaperTradingEngine) -> None:
        engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        engine.close_position(engine._positions[0].id, 55000.0)
        engine.reset()

        summary = engine.get_summary()
        assert summary.cash == 100000.0
        assert summary.total_trades == 0
        assert summary.open_positions == 0
        assert summary.total_pnl == 0.0


# ---------------------------------------------------------------------------
# Multi-symbol
# ---------------------------------------------------------------------------


class TestMultiSymbol:
    def test_positions_in_different_symbols(self, engine: PaperTradingEngine) -> None:
        result1 = engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
        result2 = engine.execute_signal("ETH-USD", "short", 10.0, 3000.0)
        assert result1["accepted"] is True
        assert result2["accepted"] is True

        summary = engine.get_summary()
        assert summary.open_positions == 2
