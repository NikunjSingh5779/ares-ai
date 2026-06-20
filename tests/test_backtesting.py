"""Tests for the backtesting engine.

Covers trade simulation, all 7 metrics, stop/take profit, commission,
slippage, and edge cases.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backtesting.engine import (
    MIN_CAPITAL,
    TRADING_DAYS_PER_YEAR,
    BacktestEngine,
    BacktestInput,
    BacktestMetrics,
    BacktestResult,
    _compute_max_drawdown,
    _compute_metrics,
    _map_signals_to_indices,
)
from backend.data.models import OHLCVData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candle(
    i: int,
    close: float = 100.0,
    symbol: str = "BTC-USD",
    interval: str = "1d",
) -> OHLCVData:
    """Create an OHLCV candle with a synthetic timestamp."""
    return OHLCVData(
        symbol=symbol,
        source="yahoo",
        interval=interval,
        timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i),
        open=close * 0.99,
        high=close * 1.02,
        low=close * 0.98,
        close=close,
        volume=10000.0,
    )


def _make_candles(n: int, start_price: float = 100.0, step: float = 0.0) -> list[OHLCVData]:
    """Generate ``n`` candles with an optional price step each day."""
    candles = []
    price = start_price
    for i in range(n):
        candles.append(_make_candle(i, close=price))
        price += step
    return candles


def _make_signal(
    direction: str,
    day: int,
    strategy: str = "test_strategy",
    **kwargs: float | str | None,
) -> dict:
    """Create a signal dict for the given day offset."""
    sig: dict = {
        "direction": direction,
        "timestamp": datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=day),
        "strategy_name": strategy,
    }
    sig.update(kwargs)
    return sig


# ---------------------------------------------------------------------------
# _map_signals_to_indices
# ---------------------------------------------------------------------------

class TestMapSignalsToIndices:
    def test_empty_signals(self):
        candles = _make_candles(10)
        assert _map_signals_to_indices([], candles) == []

    def test_empty_candles(self):
        sig = _make_signal("long", 0)
        assert _map_signals_to_indices([sig], []) == []

    def test_signal_maps_to_correct_index(self):
        candles = _make_candles(10)
        sig = _make_signal("long", 3)  # day 3 → candle index 3
        mapped = _map_signals_to_indices([sig], candles)
        assert mapped == [(3, sig)]

    def test_signal_before_first_candle_maps_to_zero(self):
        candles = _make_candles(5)
        sig = _make_signal("long", -5)  # before first candle
        mapped = _map_signals_to_indices([sig], candles)
        assert mapped[0][0] == 0

    def test_signal_after_last_candle_maps_to_last(self):
        candles = _make_candles(5)
        sig = _make_signal("long", 10)  # after last candle
        mapped = _map_signals_to_indices([sig], candles)
        assert mapped[0][0] == 4

    def test_signals_sorted_by_index(self):
        candles = _make_candles(10)
        sig1 = _make_signal("long", 5)
        sig2 = _make_signal("short", 2)
        mapped = _map_signals_to_indices([sig1, sig2], candles)
        assert [m[0] for m in mapped] == [2, 5]

    def test_signal_without_timestamp_skipped(self):
        candles = _make_candles(5)
        sig: dict = {"direction": "long"}
        mapped = _map_signals_to_indices([sig], candles)
        assert len(mapped) == 0


# ---------------------------------------------------------------------------
# _compute_max_drawdown
# ---------------------------------------------------------------------------

class TestComputeMaxDrawdown:
    def test_empty_curve(self):
        assert _compute_max_drawdown([]) == 0.0

    def test_single_value(self):
        assert _compute_max_drawdown([100.0]) == 0.0

    def test_upwards_only(self):
        assert _compute_max_drawdown([100, 110, 120, 130]) == 0.0

    def test_simple_drawdown(self):
        dd = _compute_max_drawdown([100, 110, 90, 95, 105])
        # peak=110, trough=90 → (110-90)/110*100 = 18.1818...
        assert dd == pytest.approx(18.1818, rel=1e-3)

    def test_multiple_drawdowns_takes_max(self):
        dd = _compute_max_drawdown([100, 120, 80, 100, 90])
        # peak=120, trough=80 → (120-80)/120*100 = 33.33%
        assert dd == pytest.approx(33.3333, rel=1e-3)

    def test_recovery_after_drawdown(self):
        dd = _compute_max_drawdown([100, 95, 110, 90, 120])
        # peak=110, trough=90 → (110-90)/110*100 = 18.18%
        assert dd == pytest.approx(18.1818, rel=1e-3)

    def test_peak_at_start(self):
        dd = _compute_max_drawdown([200, 180, 190, 170, 160])
        # peak=200, trough=160 → (200-160)/200*100 = 20%
        assert dd == pytest.approx(20.0, rel=1e-3)

    def test_zero_values_handled(self):
        dd = _compute_max_drawdown([0, 0, 0])
        assert dd == 0.0

    def test_negative_values_handled(self):
        dd = _compute_max_drawdown([100, -50, 50])
        # peak=100, trough=-50 → (100-(-50))/100*100 = 150%
        assert dd == pytest.approx(150.0, rel=1e-3)


# ---------------------------------------------------------------------------
# _compute_metrics
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    @staticmethod
    def _make_trade(
        pnl: float = 0.0,
        pnl_pct: float = 0.0,
        side: str = "long",
    ):
        from backtesting.engine import SimulatedTrade
        return SimulatedTrade(
            symbol="BTC-USD",
            side=side,  # type: ignore[arg-type]
            entry_price=100.0,
            exit_price=100.0 + pnl / 10.0,
            quantity=10.0,
            entry_at=datetime(2024, 1, 1, tzinfo=UTC),
            exit_at=datetime(2024, 1, 2, tzinfo=UTC),
            pnl=pnl,
            pnl_pct=pnl_pct,
        )

    def test_no_trades(self):
        metrics = _compute_metrics([], 100000.0, [100000.0])
        assert metrics.total_trades == 0
        assert metrics.final_value == 100000.0

    def test_metrics_fields_present(self):
        trades = [self._make_trade(pnl=100.0, pnl_pct=1.0)]
        metrics = _compute_metrics(trades, 100000.0, [100000.0, 101000.0])
        assert metrics.total_trades == 1
        assert metrics.winning_trades == 1
        assert metrics.gross_profit == 100.0

    def test_win_rate_50pc(self):
        trades = [
            self._make_trade(pnl=100.0, pnl_pct=1.0),
            self._make_trade(pnl=-50.0, pnl_pct=-0.5),
        ]
        metrics = _compute_metrics(trades, 100000.0, [100000.0, 101000.0, 100500.0])
        assert metrics.win_rate == 50.0
        assert metrics.losing_trades == 1

    def test_win_rate_100pc(self):
        trades = [
            self._make_trade(pnl=10.0, pnl_pct=0.1),
            self._make_trade(pnl=20.0, pnl_pct=0.2),
        ]
        metrics = _compute_metrics(trades, 100000.0, [100000.0, 100030.0])
        assert metrics.win_rate == 100.0
        assert metrics.losing_trades == 0

    def test_sharpe_ratio(self):
        trades = [
            self._make_trade(pnl=1.0, pnl_pct=0.1),
            self._make_trade(pnl=-0.5, pnl_pct=-0.05),
            self._make_trade(pnl=1.5, pnl_pct=0.15),
            self._make_trade(pnl=0.5, pnl_pct=0.05),
            self._make_trade(pnl=-1.0, pnl_pct=-0.1),
        ]
        equity = [100000.0, 100001.5]
        metrics = _compute_metrics(trades, 100000.0, equity)
        # Manual: mean(pnl_pcts) = (0.1 - 0.05 + 0.15 + 0.05 - 0.1) / 5 = 0.15/5 = 0.03
        # stdev of [0.1, -0.05, 0.15, 0.05, -0.1] ≈ 0.1
        # Sharpe = 0.03/0.1 * sqrt(252) ≈ 0.3 * 15.87 = 4.76
        pnl_pcts = [0.1, -0.05, 0.15, 0.05, -0.1]
        import statistics, math
        mean_ret = statistics.mean(pnl_pcts)
        std_ret = statistics.stdev(pnl_pcts)
        expected = mean_ret / std_ret * math.sqrt(TRADING_DAYS_PER_YEAR)
        assert metrics.sharpe_ratio == pytest.approx(expected, rel=0.01)

    def test_sharpe_single_trade_zero(self):
        trades = [self._make_trade(pnl=10.0, pnl_pct=0.1)]
        metrics = _compute_metrics(trades, 100000.0, [100000.0, 100010.0])
        assert metrics.sharpe_ratio == 0.0

    def test_sortino_ratio(self):
        trades = [
            self._make_trade(pnl=1.0, pnl_pct=0.1),
            self._make_trade(pnl=-0.5, pnl_pct=-0.05),
            self._make_trade(pnl=1.5, pnl_pct=0.15),
            self._make_trade(pnl=-1.0, pnl_pct=-0.1),
            self._make_trade(pnl=0.5, pnl_pct=0.05),
        ]
        equity = [100000.0, 100001.5]
        metrics = _compute_metrics(trades, 100000.0, equity)
        # Downside returns: [-0.05, -0.1]
        import statistics, math
        pnl_pcts = [0.1, -0.05, 0.15, -0.1, 0.05]
        mean_ret = statistics.mean(pnl_pcts)
        downside = [-0.05, -0.1]
        downside_std = statistics.stdev(downside)
        expected = mean_ret / downside_std * math.sqrt(TRADING_DAYS_PER_YEAR)
        assert metrics.sortino_ratio == pytest.approx(expected, rel=0.01)

    def test_profit_factor(self):
        trades = [
            self._make_trade(pnl=100.0, pnl_pct=1.0),
            self._make_trade(pnl=-30.0, pnl_pct=-0.3),
            self._make_trade(pnl=50.0, pnl_pct=0.5),
            self._make_trade(pnl=-20.0, pnl_pct=-0.2),
        ]
        metrics = _compute_metrics(trades, 100000.0, [100000.0, 101000.0])
        assert metrics.profit_factor == pytest.approx(150.0 / 50.0, rel=1e-3)
        assert metrics.gross_profit == 150.0
        assert metrics.gross_loss == 50.0

    def test_profit_factor_no_losses(self):
        trades = [
            self._make_trade(pnl=10.0, pnl_pct=0.1),
            self._make_trade(pnl=20.0, pnl_pct=0.2),
        ]
        metrics = _compute_metrics(trades, 100000.0, [100000.0, 100030.0])
        assert metrics.profit_factor == 999.0

    def test_expectancy(self):
        trades = [
            self._make_trade(pnl=100.0, pnl_pct=1.0),
            self._make_trade(pnl=-50.0, pnl_pct=-0.5),
            self._make_trade(pnl=200.0, pnl_pct=2.0),
        ]
        metrics = _compute_metrics(trades, 100000.0, [100000.0, 100250.0])
        assert metrics.expectancy == pytest.approx(250.0 / 3, rel=1e-3)

    def test_recovery_factor(self):
        trades = [
            self._make_trade(pnl=50.0, pnl_pct=0.5),
            self._make_trade(pnl=50.0, pnl_pct=0.5),
        ]
        # equity curve with 20% drawdown: 100k → 120k → 80k → 100k
        equity = [100000.0, 120000.0, 80000.0, 100000.0]
        metrics = _compute_metrics(trades, 100000.0, equity)
        # max_dd = (120-80)/120*100 = 33.33%
        # recovery factor = 100 / (33.33/100 * 100000) = 100 / 33333.33 = 0.003
        assert metrics.recovery_factor > 0

    def test_recovery_factor_no_drawdown(self):
        trades = [self._make_trade(pnl=10.0, pnl_pct=0.1)]
        metrics = _compute_metrics(trades, 100000.0, [100000.0, 100010.0])
        assert metrics.recovery_factor == 0.0

    def test_total_return_pct(self):
        trades = [self._make_trade(pnl=5000.0, pnl_pct=0.5)]
        metrics = _compute_metrics(trades, 100000.0, [100000.0, 105000.0])
        assert metrics.total_return_pct == pytest.approx(5.0, rel=1e-3)

    def test_negative_return(self):
        trades = [self._make_trade(pnl=-3000.0, pnl_pct=-0.3)]
        metrics = _compute_metrics(trades, 100000.0, [100000.0, 97000.0])
        assert metrics.total_return_pct == pytest.approx(-3.0, rel=1e-3)


# ---------------------------------------------------------------------------
# BacktestEngine — trade simulation
# ---------------------------------------------------------------------------

class TestBacktestEngine:
    def test_empty_candles(self):
        engine = BacktestEngine()
        result = engine.run(BacktestInput(symbol="BTC-USD", candles=[]))
        assert result.errors == ["Insufficient candles (need at least 2)"]
        assert len(result.trades) == 0

    def test_single_candle(self):
        engine = BacktestEngine()
        candles = _make_candles(1)
        result = engine.run(BacktestInput(symbol="BTC-USD", candles=candles))
        assert result.errors == ["Insufficient candles (need at least 2)"]
        assert len(result.trades) == 0

    def test_no_signals(self):
        engine = BacktestEngine()
        candles = _make_candles(10)
        result = engine.run(BacktestInput(symbol="BTC-USD", candles=candles))
        assert len(result.trades) == 0
        assert result.metrics["total_trades"] == 0

    def test_single_long_trade(self):
        engine = BacktestEngine()
        candles = _make_candles(10, start_price=100.0, step=1.0)
        signal = _make_signal("long", 0)

        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[signal],
        ))

        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade["side"] == "long"
        assert trade["symbol"] == "BTC-USD"
        assert trade["strategy_name"] == "test_strategy"
        assert trade["pnl"] > 0  # price went up

    def test_single_short_trade(self):
        engine = BacktestEngine()
        candles = _make_candles(10, start_price=100.0, step=-1.0)  # declining
        signal = _make_signal("short", 0)

        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[signal],
        ))

        assert len(result.trades) == 1
        assert result.trades[0]["side"] == "short"
        assert result.trades[0]["pnl"] > 0  # price went down, short profitable

    def test_multiple_trades(self):
        engine = BacktestEngine()
        candles = _make_candles(20, start_price=100.0, step=1.0)

        sig1 = _make_signal("long", 0)
        sig2 = _make_signal("short", 10)  # close long, open short

        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[sig1, sig2],
        ))

        assert len(result.trades) == 2
        assert result.trades[0]["side"] == "long"
        assert result.trades[1]["side"] == "short"

    def test_signals_ignored_while_position_open(self):
        """Second signal while position is open should be ignored."""
        engine = BacktestEngine()
        candles = _make_candles(20, start_price=100.0, step=1.0)

        sig1 = _make_signal("long", 0)
        sig2 = _make_signal("long", 2)  # same-day signal, ignored

        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[sig1, sig2],
        ))

        assert len(result.trades) == 1  # only one trade

    def test_equity_curve_length(self):
        engine = BacktestEngine()
        candles = _make_candles(10, start_price=100.0, step=1.0)
        signal = _make_signal("long", 0)

        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[signal],
        ))

        # equity curve length should equal number of candles processed
        assert len(result.equity_curve) == len(candles)

    def test_signals_generated_count(self):
        engine = BacktestEngine()
        candles = _make_candles(10)
        signals = [_make_signal("long", 0), _make_signal("short", 5)]
        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=signals,
        ))
        assert result.signals_generated == 2

    def test_start_end_dates(self):
        engine = BacktestEngine()
        candles = _make_candles(10)
        signal = _make_signal("long", 0)
        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[signal],
        ))
        assert result.start_date is not None
        assert result.end_date is not None


# ---------------------------------------------------------------------------
# Stop loss and take profit
# ---------------------------------------------------------------------------

class TestStopLossTakeProfit:
    def test_stop_loss_hit_long(self):
        """Long position stops out when price drops to stop loss."""
        engine = BacktestEngine()
        # Upward trend but with a dip
        candles = _make_candles(10, start_price=100.0, step=0.0)
        # Drop candle at index 3
        candles[3] = _make_candle(3, close=90.0)
        signal = _make_signal("long", 0, stop_loss=95.0)

        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[signal],
        ))

        assert len(result.trades) == 1
        if result.trades:
            assert result.trades[0]["exit_reason"] == "stop_loss"

    def test_take_profit_hit_long(self):
        """Long position takes profit when price rises to target."""
        engine = BacktestEngine()
        candles = _make_candles(10, start_price=100.0, step=5.0)  # strong uptrend
        signal = _make_signal("long", 0, take_profit=110.0)

        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[signal],
        ))

        assert len(result.trades) == 1
        if result.trades:
            assert result.trades[0]["exit_reason"] in ("take_profit",)

    def test_stop_loss_hit_short(self):
        """Short position stops out when price rises to stop loss."""
        engine = BacktestEngine()
        candles = _make_candles(10, start_price=100.0, step=0.0)
        # Spike up candle at index 2
        candles[2] = _make_candle(2, close=110.0)
        signal = _make_signal("short", 0, stop_loss=105.0)

        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[signal],
        ))

        assert len(result.trades) == 1
        if result.trades:
            assert result.trades[0]["exit_reason"] == "stop_loss"

    def test_take_profit_hit_short(self):
        """Short position takes profit when price drops to target."""
        engine = BacktestEngine()
        candles = _make_candles(10, start_price=100.0, step=-3.0)  # downtrend
        signal = _make_signal("short", 0, take_profit=95.0)

        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[signal],
        ))

        assert len(result.trades) == 1
        if result.trades:
            assert result.trades[0]["exit_reason"] in ("take_profit",)


# ---------------------------------------------------------------------------
# Commission and slippage
# ---------------------------------------------------------------------------

class TestCommissionSlippage:
    def test_commission_deducted(self):
        """Commission should reduce PnL."""
        engine = BacktestEngine()
        candles = _make_candles(5, start_price=100.0, step=5.0)

        sig_no_comm = _make_signal("long", 0)
        sig_with_comm = _make_signal("long", 0)

        result_no_comm = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[sig_no_comm],
            commission_pct=0.0,
        ))
        result_with_comm = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[sig_with_comm],
            commission_pct=0.01,
        ))

        pnl_no_comm = result_no_comm.trades[0]["pnl"]
        pnl_with_comm = result_with_comm.trades[0]["pnl"]
        assert pnl_with_comm < pnl_no_comm

    def test_slippage_affects_entry(self):
        """Slippage should affect the entry price."""
        engine = BacktestEngine()
        candles = _make_candles(5, start_price=100.0, step=0.0)
        signal = _make_signal("long", 0, entry_price=100.0)

        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[signal],
            slippage_pct=0.01,
            commission_pct=0.0,
        ))

        # Entry should be 100 * 1.01 = 101 (slippage adds for long)
        assert result.trades[0]["entry_price"] == pytest.approx(101.0, rel=1e-3)

    def test_slippage_short_entry(self):
        """Short entry should have slippage subtracted."""
        engine = BacktestEngine()
        candles = _make_candles(5, start_price=100.0, step=0.0)
        signal = _make_signal("short", 0, entry_price=100.0)

        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[signal],
            slippage_pct=0.01,
            commission_pct=0.0,
        ))

        # Entry should be 100 * 0.99 = 99 (slippage subtracts for short)
        assert result.trades[0]["entry_price"] == pytest.approx(99.0, rel=1e-3)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_min_capital_floor(self):
        """Zero initial capital should be clamped to MIN_CAPITAL."""
        engine = BacktestEngine()
        candles = _make_candles(5)
        signal = _make_signal("long", 0)

        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[signal],
            initial_capital=0.0,
        ))

        assert result.metrics["initial_capital"] == MIN_CAPITAL

    def test_negative_initial_capital(self):
        """Negative capital should be clamped to MIN_CAPITAL."""
        engine = BacktestEngine()
        candles = _make_candles(5)
        signal = _make_signal("long", 0)

        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[signal],
            initial_capital=-5000.0,
        ))

        assert result.metrics["initial_capital"] == MIN_CAPITAL

    def test_dict_input_accepted(self):
        """Engine should accept a raw dict as input."""
        engine = BacktestEngine()
        candles = _make_candles(3)
        result = engine.run({
            "symbol": "BTC-USD",
            "candles": candles,
        })
        assert isinstance(result, BacktestResult)
        assert result.symbol == "BTC-USD"

    def test_result_fields_present(self):
        """BacktestResult should have all expected fields."""
        candles = _make_candles(10)
        signal = _make_signal("long", 0)
        engine = BacktestEngine()
        result = engine.run(BacktestInput(
            symbol="BTC-USD", candles=candles, signals=[signal],
        ))

        assert result.symbol == "BTC-USD"
        assert "sharpe_ratio" in result.metrics
        assert "sortino_ratio" in result.metrics
        assert "win_rate" in result.metrics
        assert "profit_factor" in result.metrics
        assert "max_drawdown_pct" in result.metrics
        assert "total_trades" in result.metrics
        assert "expectancy" in result.metrics
        assert "recovery_factor" in result.metrics
        assert "total_return_pct" in result.metrics
        assert result.trades is not None
        assert result.equity_curve is not None
        assert result.signals_generated == 1

    def test_backtest_metrics_dataclass_defaults(self):
        """BacktestMetrics should have sensible defaults for 0-trade case."""
        metrics = BacktestMetrics()
        assert metrics.total_trades == 0
        assert metrics.sharpe_ratio == 0.0
        assert metrics.sortino_ratio == 0.0
        assert metrics.win_rate == 0.0
        assert metrics.profit_factor == 0.0
        assert metrics.max_drawdown_pct == 0.0
        assert metrics.expectancy == 0.0
        assert metrics.recovery_factor == 0.0
