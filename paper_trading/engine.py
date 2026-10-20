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

import uuid
from dataclasses import dataclass
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
    entry_commission: float = 0.0
    margin: float = 0.0


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
    entry_commission: float = 0.0
    exit_commission: float = 0.0


@dataclass
class PortfolioSummary:
    """Snapshot of paper portfolio state and performance.

    ``cash`` includes proceeds credited from open short positions. ``margin_used``
    is the notional reserved against those shorts; ``equity`` is cash plus the
    mark-to-market value of long positions minus the liability of short positions.
    """

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
    equity: float = 0.0
    margin_used: float = 0.0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class PaperTradingEngine:
    """In-memory paper trading portfolio manager.

    Maintains cash balance, open positions, and closed-trade history.
    Supports long/short entries, stop-loss/take-profit checks per candle,
    and reversal signals.
    """

    def __init__(
        self,
        initial_capital: float = 100000.0,
        commission_pct: float = 0.0,
        slippage_pct: float = 0.0,
    ) -> None:
        """Create a paper portfolio.

        ``commission_pct`` and ``slippage_pct`` are expressed as decimals
        (0.001 = 10 bps). They default to zero so direct unit tests can model
        frictionless fills; the application wires the configured defaults from
        ``configs.settings`` into its shared engine.
        """
        if not 0.0 <= commission_pct < 1.0:
            raise ValueError("commission_pct must be between 0 and 1")
        if not 0.0 <= slippage_pct < 1.0:
            raise ValueError("slippage_pct must be between 0 and 1")

        self._initial_capital = max(initial_capital, 1000.0)
        self._cash: float = self._initial_capital
        self._commission_pct = commission_pct
        self._slippage_pct = slippage_pct
        self._positions: list[PaperPosition] = []
        self._closed_trades: list[ClosedTrade] = []
        self._equity_curve: list[float] = [self._initial_capital]
        self._last_prices: dict[str, float] = {}

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
        if side not in ("long", "short"):
            return {"accepted": False, "reason": "Side must be 'long' or 'short'"}
        if quantity <= 0:
            return {"accepted": False, "reason": "Quantity must be positive"}
        if entry_price <= 0:
            return {"accepted": False, "reason": "Entry price must be positive"}

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
            if closed is not None:
                result["closed_trade"] = self._trade_to_dict(closed)

        # Apply adverse slippage to the signal price. A long pays up; a short
        # receives less. This is the actual fill recorded on the position.
        fill_price = (
            entry_price * (1.0 + self._slippage_pct) if side == "long" else entry_price * (1.0 - self._slippage_pct)
        )
        if fill_price <= 0:
            return {"accepted": False, "reason": "Invalid fill price after slippage"}

        # Longs are limited by free cash and by equity not already reserved as
        # short margin. Shorts require 100% notional margin, so their notional
        # cannot exceed current free margin. Both budgets include commission.
        equity = self._compute_equity()
        margin_used = sum(pos.margin for pos in self._positions)
        free_margin = max(equity - margin_used, 0.0)
        buying_power = min(self._cash, free_margin) if side == "long" else free_margin
        max_affordable = max(buying_power, 0.0) / (fill_price * (1.0 + self._commission_pct))
        actual_quantity = min(quantity, max_affordable)
        if actual_quantity <= 0:
            return {"accepted": False, "reason": "Insufficient cash"}

        notional = actual_quantity * fill_price
        entry_commission = notional * self._commission_pct
        if side == "long":
            self._cash -= notional + entry_commission
            margin = 0.0
        else:
            # Credit short proceeds and reserve the notional as margin. The
            # margin is reported for exposure control; cash stays net of fees.
            self._cash += notional - entry_commission
            margin = notional

        pos = PaperPosition(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,  # type: ignore[arg-type]
            quantity=actual_quantity,
            entry_price=fill_price,
            entry_at=datetime.now(),
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_name=strategy_name,
            entry_commission=entry_commission,
            margin=margin,
        )
        self._positions.append(pos)
        self._last_prices[symbol] = fill_price
        self._equity_curve.append(self._compute_equity())
        result["position_id"] = pos.id
        result["fill_price"] = fill_price
        result["quantity"] = actual_quantity
        result["commission"] = entry_commission
        result["margin"] = margin

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
            exit_price: Reference price at which the position is exited;
                adverse slippage and commission are applied to the fill.
            exit_reason: Reason for closing (``"signal"``, ``"stop_loss"``,
                ``"take_profit"``).

        Returns:
            The ``ClosedTrade`` record, or ``None`` if position not found.
        """
        if exit_price <= 0:
            return None

        for i, pos in enumerate(self._positions):
            if pos.id == position_id:
                self._positions.pop(i)

                # Exit fills are adverse: a long sells lower; a short buys higher.
                exit_fill = (
                    exit_price * (1.0 - self._slippage_pct)
                    if pos.side == "long"
                    else exit_price * (1.0 + self._slippage_pct)
                )
                if exit_fill <= 0:
                    # Restore the position rather than recording an invalid fill.
                    self._positions.insert(i, pos)
                    return None

                exit_value = pos.quantity * exit_fill
                exit_commission = exit_value * self._commission_pct
                if pos.side == "long":
                    price_pnl = pos.quantity * (exit_fill - pos.entry_price)
                    self._cash += exit_value - exit_commission
                else:
                    price_pnl = pos.quantity * (pos.entry_price - exit_fill)
                    self._cash -= exit_value + exit_commission

                pnl = price_pnl - pos.entry_commission - exit_commission
                entry_value = pos.quantity * pos.entry_price
                pnl_pct = (pnl / entry_value * 100.0) if entry_value > 0 else 0.0

                trade = ClosedTrade(
                    symbol=pos.symbol,
                    side=pos.side,
                    quantity=pos.quantity,
                    entry_price=pos.entry_price,
                    exit_price=exit_fill,
                    entry_at=pos.entry_at,
                    exit_at=datetime.now(),
                    pnl=round(pnl, 2),
                    pnl_pct=round(pnl_pct, 4),
                    exit_reason=exit_reason,
                    strategy_name=pos.strategy_name,
                    entry_commission=pos.entry_commission,
                    exit_commission=exit_commission,
                )
                self._closed_trades.append(trade)
                self._last_prices.pop(pos.symbol, None)

                # Track equity after the position is removed.
                self._equity_curve.append(self._compute_equity())

                return trade

        return None

    def check_sl_tp(self, symbol: str, high: float, low: float) -> list[ClosedTrade]:
        """Check open positions for a symbol against a candle's high/low for SL/TP.

        Args:
            symbol: Ticker symbol.
            high: Current candle's high price.
            low: Current candle's low price.

        Returns:
            List of ``ClosedTrade`` records for any positions that were
            stopped out or took profit.
        """
        closed: list[ClosedTrade] = []

        for pos in list(self._positions):
            if pos.symbol != symbol:
                continue

            exit_price: float | None = None
            reason: str | None = None

            # If a candle spans both levels, the intra-candle path is unknown.
            # Assume the adverse level was reached first; optimistic ordering
            # would inflate paper results and distort the promotion gate.
            if pos.side == "long":
                if pos.stop_loss is not None and low <= pos.stop_loss:
                    exit_price = pos.stop_loss
                    reason = "stop_loss"
                elif pos.take_profit is not None and high >= pos.take_profit:
                    exit_price = pos.take_profit
                    reason = "take_profit"
            else:  # short
                if pos.stop_loss is not None and high >= pos.stop_loss:
                    exit_price = pos.stop_loss
                    reason = "stop_loss"
                elif pos.take_profit is not None and low <= pos.take_profit:
                    exit_price = pos.take_profit
                    reason = "take_profit"

            if reason is not None and exit_price is not None:
                trade = self.close_position(pos.id, exit_price, exit_reason=reason)
                if trade is not None:
                    closed.append(trade)

        return closed

    def mark_to_market(self, symbol: str, price: float) -> None:
        """Mark open positions for ``symbol`` at the latest market price.

        Appending the resulting equity to the curve is what makes intra-trade
        drawdown measurable. Calling this with a symbol that has no open
        position is a no-op.
        """
        if price <= 0:
            return
        if not any(pos.symbol == symbol for pos in self._positions):
            return
        self._last_prices[symbol] = price
        self._equity_curve.append(self._compute_equity())

    def get_summary(self) -> PortfolioSummary:
        """Compute portfolio-level metrics at the latest marks.

        ``total_pnl`` includes unrealized PnL and is derived from equity, so it
        reconciles with the cash and open-position marks rather than summing
        only closed trades.
        """
        equity = self._compute_equity()
        total_pnl = equity - self._initial_capital
        total_return_pct = (equity / self._initial_capital - 1.0) * 100.0

        wins = [t for t in self._closed_trades if t.pnl > 0]
        losses = [t for t in self._closed_trades if t.pnl < 0]
        n = len(self._closed_trades)

        win_rate = (len(wins) / n * 100.0) if n > 0 else 0.0
        max_dd = self._compute_max_drawdown()
        margin_used = sum(pos.margin for pos in self._positions)

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
            equity=round(equity, 2),
            margin_used=round(margin_used, 2),
        )

    def reset(self) -> None:
        """Reset the portfolio to its initial state."""
        self._cash = self._initial_capital
        self._positions.clear()
        self._closed_trades.clear()
        self._equity_curve = [self._initial_capital]
        self._last_prices.clear()

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
        """Compute total portfolio equity at the latest marks.

        Longs add market value to cash. Shorts subtract their liability, while
        their credited proceeds remain in cash. At entry this reduces equity by
        the entry commission only, which is the correct accounting identity.
        """
        equity = self._cash
        for pos in self._positions:
            mark = self._last_prices.get(pos.symbol, pos.entry_price)
            if pos.side == "long":
                equity += pos.quantity * mark
            else:
                equity -= pos.quantity * mark
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
            "entry_commission": round(trade.entry_commission, 8),
            "exit_commission": round(trade.exit_commission, 8),
            "fees": round(trade.entry_commission + trade.exit_commission, 2),
        }
