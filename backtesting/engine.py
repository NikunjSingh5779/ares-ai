"""Backtest Engine — historical trade simulation and performance metrics.

Pure-Python simulation that accepts OHLCV candles and signals, simulates
trade execution with commission and slippage, and computes standard
performance metrics matching the ``backtests`` database table schema.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.data.models import OHLCVData


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRADING_DAYS_PER_YEAR: float = 252.0
"""Number of trading days used for annualizing Sharpe/Sortino ratios."""

MIN_CAPITAL: float = 1000.0
"""Floor for initial capital (clamped if zero or negative)."""


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Signal = dict[str, Any]
"""Backtest signal dict.

Required keys:
    direction : Literal["long", "short"]
        Trade direction.
    timestamp : datetime
        When the signal was generated (used to match to a candle).
    strategy_name : str
        Name of the strategy that generated this signal.

Optional keys:
    entry_price : float | None
        Fixed entry price. If None, uses next candle's open.
    stop_loss : float | None
        Stop-loss price level.
    take_profit : float | None
        Take-profit price level.
    confidence : float
        Signal confidence (0-100). Defaults to 50.
"""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SimulatedTrade:
    """A single closed trade from the simulation."""

    symbol: str
    side: Literal["long", "short"]
    entry_price: float
    exit_price: float
    quantity: float
    entry_at: datetime
    exit_at: datetime
    pnl: float
    pnl_pct: float
    exit_reason: str = "signal"
    strategy_name: str = ""


@dataclass
class BacktestMetrics:
    """Computed performance metrics from a backtest run.

    All fields match the ``backtests`` database table columns.
    """

    total_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    expectancy: float = 0.0
    recovery_factor: float = 0.0
    initial_capital: float = 100000.0
    final_value: float = 100000.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0


class BacktestInput(BaseModel):
    """Input parameters for a backtest run."""

    symbol: str = Field(..., description="Ticker symbol")
    candles: list[OHLCVData] = Field(
        default_factory=list,
        description="OHLCV candles in chronological order (oldest first)",
    )
    initial_capital: float = Field(
        default=100000.0,
        description="Starting capital in USD (clamped to MIN_CAPITAL if <= 0)",
    )
    commission_pct: float = Field(
        default=0.001,
        ge=0,
        le=1,
        description="Commission per trade as fraction (e.g. 0.001 = 0.1%%)",
    )
    slippage_pct: float = Field(
        default=0.001,
        ge=0,
        le=1,
        description="Slippage per trade as fraction applied to entry and exit",
    )
    signals: list[Signal] = Field(
        default_factory=list,
        description="List of signal dicts in chronological order",
    )


class BacktestResult(BaseModel):
    """Full result from a backtest run."""

    symbol: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    trades: list[dict[str, Any]] = Field(default_factory=list)
    equity_curve: list[float] = Field(default_factory=list)
    signals_generated: int = 0
    start_date: str | None = None
    end_date: str | None = None
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Position tracking
# ---------------------------------------------------------------------------


@dataclass
class _Position:
    """Internal position tracker during simulation."""

    side: Literal["long", "short"]
    entry_price: float
    quantity: float
    entry_index: int
    entry_at: datetime
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy_name: str = ""


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------


def _compute_metrics(
    trades: list[SimulatedTrade],
    initial_capital: float,
    equity_curve: list[float],
) -> BacktestMetrics:
    """Compute all performance metrics from the trade list.

    Handles edge cases: 0 trades, 1 trade (no variance), div/0, NaN.
    """
    n_trades = len(trades)
    if n_trades == 0:
        final_value = equity_curve[-1] if equity_curve else initial_capital
        return BacktestMetrics(initial_capital=initial_capital, final_value=final_value)

    pnl_values = [t.pnl for t in trades]
    pnl_pcts = [t.pnl_pct for t in trades]

    gross_profit = sum(p for p in pnl_values if p > 0)
    gross_loss = abs(sum(p for p in pnl_values if p < 0))
    winning = [p for p in pnl_values if p > 0]
    losing = [p for p in pnl_values if p < 0]
    win_count = len(winning)
    loss_count = len(losing)

    total_return_pct = (equity_curve[-1] / initial_capital - 1.0) * 100.0

    # Sharpe ratio (annualized)
    if n_trades >= 2:
        mean_ret = statistics.mean(pnl_pcts)
        std_ret = statistics.stdev(pnl_pcts)
        sharpe = (mean_ret / std_ret * math.sqrt(TRADING_DAYS_PER_YEAR)) if std_ret > 0 else 0.0
    else:
        sharpe = 0.0

    # Sortino ratio (annualized, uses downside deviation only)
    if n_trades >= 2:
        downside = [r for r in pnl_pcts if r < 0]
        if downside:
            downside_std = statistics.stdev(downside) if len(downside) >= 2 else (downside[0] if downside else 0.0)
        else:
            downside_std = 0.0
        sortino = (mean_ret / downside_std * math.sqrt(TRADING_DAYS_PER_YEAR)) if downside_std > 0 else 0.0
    else:
        sortino = 0.0

    # Win rate
    win_rate = (win_count / n_trades * 100.0) if n_trades > 0 else 0.0

    # Profit factor
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = 999.0 if gross_profit > 0 else 0.0

    # Max drawdown from equity curve
    max_dd = _compute_max_drawdown(equity_curve)

    # Expectancy
    expectancy = statistics.mean(pnl_values) if n_trades > 0 else 0.0

    # Recovery factor
    if max_dd > 0:
        total_pnl = sum(pnl_values)
        recovery_factor = total_pnl / abs(max_dd / 100.0 * initial_capital) if max_dd != 0 else 0.0
    else:
        recovery_factor = 0.0

    return BacktestMetrics(
        total_return_pct=round(total_return_pct, 4),
        sharpe_ratio=round(sharpe, 4),
        sortino_ratio=round(sortino, 4),
        win_rate=round(win_rate, 2),
        profit_factor=round(profit_factor, 4),
        max_drawdown_pct=round(max_dd, 4),
        total_trades=n_trades,
        winning_trades=win_count,
        losing_trades=loss_count,
        expectancy=round(expectancy, 2),
        recovery_factor=round(recovery_factor, 4),
        initial_capital=initial_capital,
        final_value=round(equity_curve[-1], 2),
        gross_profit=round(gross_profit, 2),
        gross_loss=round(gross_loss, 2),
    )


def _compute_max_drawdown(equity_curve: list[float]) -> float:
    """Compute maximum drawdown percentage from an equity curve.

    Returns 0.0 for flat or upwards-only curves.
    """
    if len(equity_curve) < 2:
        return 0.0

    peak = equity_curve[0]
    max_dd = 0.0

    for value in equity_curve:
        if value > peak:
            peak = value
        dd = (peak - value) / peak * 100.0 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    return max_dd


# ---------------------------------------------------------------------------
# Signal-to-candle mapping
# ---------------------------------------------------------------------------


def _map_signals_to_indices(
    signals: list[Signal],
    candles: list[OHLCVData],
) -> list[tuple[int, Signal]]:
    """Map each signal to the candle index where it should be evaluated.

    A signal is evaluated at the candle whose timestamp is **on or after**
    the signal's timestamp. If the signal falls before the first candle, it
    maps to index 0.

    Returns list of (candle_index, signal) sorted by candle index.
    """
    if not signals or not candles:
        return []

    mapped: list[tuple[int, Signal]] = []

    for sig in signals:
        sig_ts = sig.get("timestamp")
        if sig_ts is None:
            continue

        # Find the first candle at or after this signal's timestamp
        found = False
        for idx, candle in enumerate(candles):
            if candle.timestamp >= sig_ts:
                mapped.append((idx, sig))
                found = True
                break

        if not found:
            # Signal is after the last candle — map to last index
            mapped.append((len(candles) - 1, sig))

    # Sort by candle index, then by signal timestamp
    mapped.sort(key=lambda x: (x[0], x[1].get("timestamp", datetime.min)))
    return mapped


# ---------------------------------------------------------------------------
# Backtest Engine
# ---------------------------------------------------------------------------


class BacktestEngine:
    """Pure-Python backtesting engine.

    Simulates trade execution against historical OHLCV data using a list of
    entry/exit signals, managing a single position at a time with optional
    stop-loss and take-profit levels.

    Usage::

        engine = BacktestEngine()
        result = engine.run(BacktestInput(symbol="BTC-USD", candles=..., signals=...))
    """

    def run(
        self,
        input_data: BacktestInput | dict[str, Any],
    ) -> BacktestResult:
        """Run the backtest simulation.

        Args:
            input_data: ``BacktestInput`` instance or dict of keyword args.

        Returns:
            ``BacktestResult`` with trades, metrics, and equity curve.
        """
        if isinstance(input_data, dict):
            input_data = BacktestInput(**input_data)

        symbol = input_data.symbol
        candles = input_data.candles
        initial_capital = max(input_data.initial_capital, MIN_CAPITAL)
        commission = input_data.commission_pct
        slippage = input_data.slippage_pct
        signals = input_data.signals

        # --- Early exits ---
        errors: list[str] = []

        if len(candles) < 2:
            errors.append("Insufficient candles (need at least 2)")
            return BacktestResult(
                symbol=symbol,
                equity_curve=[initial_capital],
                errors=errors,
            )

        # Sort and map signals to candle indices
        sorted_signals = sorted(signals, key=lambda s: s.get("timestamp", datetime.min))
        signal_map = _map_signals_to_indices(sorted_signals, candles)
        # Track which signal indices we've consumed
        next_signal_idx = 0

        # --- Simulation state ---
        cash: float = initial_capital
        position: _Position | None = None
        trades: list[SimulatedTrade] = []
        equity_curve: list[float] = [initial_capital]

        n = len(candles)

        for i in range(n - 1):  # -1 because we need candle[i+1] for entry/exit
            candle = candles[i]
            next_candle = candles[i + 1]

            # --- Check open position: stop loss / take profit ---
            if position is not None:
                reason: str | None = None

                if position.side == "long":
                    if position.take_profit is not None and candle.high >= position.take_profit:
                        exit_price = position.take_profit * (1 - slippage)
                        reason = "take_profit"
                    elif position.stop_loss is not None and candle.low <= position.stop_loss:
                        exit_price = position.stop_loss * (1 - slippage)
                        reason = "stop_loss"
                else:  # short
                    if position.take_profit is not None and candle.low <= position.take_profit:
                        exit_price = position.take_profit * (1 + slippage)
                        reason = "take_profit"
                    elif position.stop_loss is not None and candle.high >= position.stop_loss:
                        exit_price = position.stop_loss * (1 + slippage)
                        reason = "stop_loss"

                if reason:
                    self._close_position(
                        position, candle, exit_price, commission, trades,
                        exit_reason=reason,
                    )
                    cash = self._cash_after_close(position, exit_price, commission)
                    position = None

            # --- Process signals mapped to this candle index ---
            while next_signal_idx < len(signal_map) and signal_map[next_signal_idx][0] == i:
                _, signal = signal_map[next_signal_idx]
                next_signal_idx += 1

                signal_dir = signal.get("direction", "long")

                # Same-direction signal while position open → ignore
                if position is not None and signal_dir == position.side:
                    continue

                # Close existing position if open (reversal signal)
                if position is not None:
                    exit_price = candle.close * (1 - slippage) if position.side == "long" else candle.close * (1 + slippage)
                    self._close_position(
                        position, candle, exit_price, commission, trades,
                        exit_reason="signal",
                    )
                    cash = self._cash_after_close(position, exit_price, commission)
                    position = None

                # Enter new position at next candle's open
                entry_price = signal.get("entry_price") or next_candle.open
                if signal_dir == "long":
                    entry_price *= (1 + slippage)
                else:
                    entry_price *= (1 - slippage)

                # Position size: account for commission so cash doesn't go negative
                quantity = cash / (entry_price * (1 + commission))
                cost = quantity * entry_price
                commission_cost = cost * commission
                cash -= cost + commission_cost

                position = _Position(
                    side=signal_dir,
                    entry_price=entry_price,
                    quantity=quantity,
                    entry_index=i + 1,
                    entry_at=next_candle.timestamp,
                    stop_loss=signal.get("stop_loss"),
                    take_profit=signal.get("take_profit"),
                    strategy_name=signal.get("strategy_name", ""),
                )

            # --- Track equity ---
            equity = self._compute_equity(cash, position, candle)
            equity_curve.append(equity)

        # --- Close any open position at the last candle ---
        if position is not None and n > 0:
            last = candles[-1]
            exit_price = last.close
            exit_price *= (1 - slippage) if position.side == "long" else (1 + slippage)
            self._close_position(position, last, exit_price, commission, trades)
            cash = self._cash_after_close(position, exit_price, commission)
            position = None

            equity = self._compute_equity(cash, None, last)
            equity_curve[-1] = equity

        # --- Compute metrics ---
        metrics = _compute_metrics(trades, initial_capital, equity_curve)

        return BacktestResult(
            symbol=symbol,
            metrics=metrics.__dict__,
            trades=[self._trade_to_dict(t) for t in trades],
            equity_curve=equity_curve,
            signals_generated=len(signals),
            start_date=candles[0].timestamp.isoformat() if candles else None,
            end_date=candles[-1].timestamp.isoformat() if candles else None,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _close_position(
        position: _Position,
        candle: OHLCVData,
        exit_price: float,
        commission_pct: float,
        trades: list[SimulatedTrade],
        exit_reason: str = "signal",
    ) -> None:
        """Close a position, compute PnL, and append a SimulatedTrade."""
        if position.side == "long":
            pnl = position.quantity * (exit_price - position.entry_price)
        else:
            pnl = position.quantity * (position.entry_price - exit_price)

        # Deduct commission on exit
        commission_cost = position.quantity * exit_price * commission_pct
        pnl -= commission_cost

        entry_value = position.quantity * position.entry_price
        pnl_pct = (pnl / entry_value * 100.0) if entry_value > 0 else 0.0

        trades.append(SimulatedTrade(
            symbol=candle.symbol,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            entry_at=position.entry_at,
            exit_at=candle.timestamp,
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 4),
            exit_reason=exit_reason,
            strategy_name=position.strategy_name,
        ))

    @staticmethod
    def _cash_after_close(
        position: _Position,
        exit_price: float,
        commission_pct: float,
    ) -> float:
        """Calculate cash after closing a position."""
        if position.side == "long":
            proceeds = position.quantity * exit_price
            commission_cost = proceeds * commission_pct
            return proceeds - commission_cost
        else:
            # For short positions, return initial entry value + PnL
            entry_value = position.quantity * position.entry_price
            pnl = position.quantity * (position.entry_price - exit_price)
            exit_value = position.quantity * exit_price
            commission_cost = exit_value * commission_pct
            return entry_value + pnl - commission_cost

    @staticmethod
    def _compute_equity(
        cash: float,
        position: _Position | None,
        candle: OHLCVData,
    ) -> float:
        """Compute total equity (cash + position market value)."""
        if position is None:
            return cash
        
        if position.side == "long":
            market_value = position.quantity * candle.close
            return cash + market_value
        else:
            entry_value = position.quantity * position.entry_price
            pnl = position.quantity * (position.entry_price - candle.close)
            return cash + entry_value + pnl

    @staticmethod
    def _trade_to_dict(trade: SimulatedTrade) -> dict[str, Any]:
        """Convert a SimulatedTrade to a dict for JSON serialization."""
        return {
            "symbol": trade.symbol,
            "side": trade.side,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "quantity": trade.quantity,
            "entry_at": trade.entry_at.isoformat(),
            "exit_at": trade.exit_at.isoformat(),
            "pnl": trade.pnl,
            "pnl_pct": trade.pnl_pct,
            "exit_reason": trade.exit_reason,
            "strategy_name": trade.strategy_name,
        }
