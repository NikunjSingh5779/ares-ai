"""Paper Trading Engine — simulated forward trade execution.

Manages an in-memory paper portfolio: opens/closes positions,
checks stop-loss/take-profit against incoming candle data,
and tracks portfolio-level metrics.

Usage::

    engine = PaperTradingEngine(initial_capital=100000.0)
    engine.execute_signal("BTC-USD", "long", 1.0, 50000.0)
    closed = engine.check_sl_tp(candle)
    summary = engine.get_summary()
"""

from __future__ import annotations

import math
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PaperPosition:
    """An open paper trading position."""

    id: str
    symbol: str
    side: Literal["long", "short"]
    quantity: float
    entry_price: float
    entry_at: datetime
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy_name: str = ""


@dataclass
class ClosedTrade:
    """A completed (closed) paper trade."""

    symbol: str
    side: Literal["long", "short"]
    quantity: float
    entry_price: float
    exit_price: float
    entry_at: datetime
    exit_at: datetime
    pnl: float
    pnl_pct: float
    exit_reason: str = "signal"
    strategy_name: str = ""


@dataclass
class PortfolioSummary:
    """Snapshot of paper portfolio state and performance."""

    initial_capital: float
    cash: float
    total_pnl: float
    total_return_pct: float
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    open_positions: int
    max_drawdown_pct: float = 0.0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class PaperTradingEngine:
    """In-memory paper trading portfolio manager.

    Maintains cash balance, open positions, and closed-trade history.
    Supports long/short entries, stop-loss/take-profit checks per candle,
    and reversal signals.
    """

    def __init__(self, initial_capital: float = 100000.0) -> None:
        self._initial_capital = max(initial_capital, 1000.0)
        self._cash: float = self._initial_capital
        self._positions: list[PaperPosition] = []
        self._closed_trades: list[ClosedTrade] = []
        self._equity_curve: list[float] = [self._initial_capital]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_signal(
        self,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        strategy_name: str = "",
    ) -> dict[str, Any]:
        """Execute a trade signal against the paper portfolio.

        Args:
            symbol: Ticker symbol.
            side: ``"long"`` or ``"short"``.
            quantity: Number of units to trade.
            entry_price: Price per unit at entry.
            stop_loss: Optional stop-loss price level.
            take_profit: Optional take-profit price level.
            strategy_name: Name of the strategy producing this signal.

        Returns:
            Dict with keys ``accepted``, ``position_id``, ``reversal``,
            ``closed_trade``, and ``reason``.
        """
        if quantity <= 0:
            return {"accepted": False, "reason": "Quantity must be positive"}

        result: dict[str, Any] = {
            "accepted": True,
            "position_id": None,
            "reversal": False,
            "closed_trade": None,
            "reason": "ok",
        }

        # Check for existing position in the same symbol
        existing = self._find_position(symbol)

        if existing is not None:
            if existing.side == side:
                # Same direction — ignore
                return {"accepted": False, "reason": f"Already in {side} position for {symbol}"}

            # Opposite direction — close existing, open new
            closed = self.close_position(existing.id, entry_price, exit_reason="signal")
            result["reversal"] = True
            result["closed_trade"] = self._trade_to_dict(closed)

        # Open new position (only spend up to cash)
        position_value = min(quantity * entry_price, self._cash)
        actual_quantity = position_value / entry_price if entry_price > 0 else 0.0

        if actual_quantity <= 0:
            return {"accepted": False, "reason": "Insufficient cash"}

        pos = PaperPosition(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,  # type: ignore[arg-type]
            quantity=actual_quantity,
            entry_price=entry_price,
            entry_at=datetime.now(),
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_name=strategy_name,
        )
        self._positions.append(pos)
        self._cash -= position_value
        result["position_id"] = pos.id

        return result

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str = "signal",
    ) -> ClosedTrade | None:
        """Close an open position and record the trade.

        Args:
            position_id: UUID of the position to close.
            exit_price: Price at which the position is exited.
            exit_reason: Reason for closing (``"signal"``, ``"stop_loss"``,
                ``"take_profit"``).

        Returns:
            The ``ClosedTrade`` record, or ``None`` if position not found.
        """
        for i, pos in enumerate(self._positions):
            if pos.id == position_id:
                self._positions.pop(i)

                if pos.side == "long":
                    pnl = pos.quantity * (exit_price - pos.entry_price)
                else:
                    pnl = pos.quantity * (pos.entry_price - exit_price)

                entry_value = pos.quantity * pos.entry_price
                pnl_pct = (pnl / entry_value * 100.0) if entry_value > 0 else 0.0

                self._cash += pos.quantity * exit_price

                trade = ClosedTrade(
                    symbol=pos.symbol,
                    side=pos.side,
                    quantity=pos.quantity,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    entry_at=pos.entry_at,
                    exit_at=datetime.now(),
                    pnl=round(pnl, 2),
                    pnl_pct=round(pnl_pct, 4),
                    exit_reason=exit_reason,
                    strategy_name=pos.strategy_name,
                )
                self._closed_trades.append(trade)

                # Track equity
                self._equity_curve.append(self._compute_equity())

                return trade

        return None

    def check_sl_tp(self, high: float, low: float) -> list[ClosedTrade]:
        """Check all open positions against a candle's high/low for SL/TP.

        Args:
            high: Current candle's high price.
            low: Current candle's low price.

        Returns:
            List of ``ClosedTrade`` records for any positions that were
            stopped out or took profit.
        """
        closed: list[ClosedTrade] = []

        for pos in list(self._positions):
            exit_price: float | None = None
            reason: str | None = None

            if pos.side == "long":
                if pos.take_profit is not None and high >= pos.take_profit:
                    exit_price = pos.take_profit
                    reason = "take_profit"
                elif pos.stop_loss is not None and low <= pos.stop_loss:
                    exit_price = pos.stop_loss
                    reason = "stop_loss"
            else:  # short
                if pos.take_profit is not None and low <= pos.take_profit:
                    exit_price = pos.take_profit
                    reason = "take_profit"
                elif pos.stop_loss is not None and high >= pos.stop_loss:
                    exit_price = pos.stop_loss
                    reason = "stop_loss"

            if reason is not None and exit_price is not None:
                trade = self.close_position(pos.id, exit_price, exit_reason=reason)
                if trade is not None:
                    closed.append(trade)

        return closed

    def get_summary(self) -> PortfolioSummary:
        """Compute portfolio-level metrics.

        Returns:
            ``PortfolioSummary`` with PnL, return %, win rate, drawdown.
        """
        total_pnl = sum(t.pnl for t in self._closed_trades)
        total_return_pct = (self._compute_equity() / self._initial_capital - 1.0) * 100.0

        wins = [t for t in self._closed_trades if t.pnl > 0]
        losses = [t for t in self._closed_trades if t.pnl < 0]
        n = len(self._closed_trades)

        win_rate = (len(wins) / n * 100.0) if n > 0 else 0.0
        max_dd = self._compute_max_drawdown()

        return PortfolioSummary(
            initial_capital=self._initial_capital,
            cash=round(self._cash, 2),
            total_pnl=round(total_pnl, 2),
            total_return_pct=round(total_return_pct, 4),
            win_rate=round(win_rate, 2),
            total_trades=n,
            winning_trades=len(wins),
            losing_trades=len(losses),
            open_positions=len(self._positions),
            max_drawdown_pct=round(max_dd, 4),
        )

    def reset(self) -> None:
        """Reset the portfolio to its initial state."""
        self._cash = self._initial_capital
        self._positions.clear()
        self._closed_trades.clear()
        self._equity_curve = [self._initial_capital]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_position(self, symbol: str) -> PaperPosition | None:
        """Find an open position for the given symbol."""
        for pos in self._positions:
            if pos.symbol == symbol:
                return pos
        return None

    def _compute_equity(self) -> float:
        """Compute total portfolio equity (cash + open position values)."""
        equity = self._cash
        for pos in self._positions:
            equity += pos.quantity * pos.entry_price  # mark-to-market at entry for simplicity
        return equity

    def _compute_max_drawdown(self) -> float:
        """Compute maximum drawdown percentage from the equity curve."""
        if len(self._equity_curve) < 2:
            return 0.0

        peak = self._equity_curve[0]
        max_dd = 0.0

        for value in self._equity_curve:
            if value > peak:
                peak = value
            dd = (peak - value) / peak * 100.0 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        return max_dd

    @staticmethod
    def _trade_to_dict(trade: ClosedTrade) -> dict[str, Any]:
        """Convert a ClosedTrade to a JSON-serializable dict."""
        return {
            "symbol": trade.symbol,
            "side": trade.side,
            "quantity": trade.quantity,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "entry_at": trade.entry_at.isoformat() if hasattr(trade.entry_at, "isoformat") else str(trade.entry_at),
            "exit_at": trade.exit_at.isoformat() if hasattr(trade.exit_at, "isoformat") else str(trade.exit_at),
            "pnl": trade.pnl,
            "pnl_pct": trade.pnl_pct,
            "exit_reason": trade.exit_reason,
            "strategy_name": trade.strategy_name,
        }
