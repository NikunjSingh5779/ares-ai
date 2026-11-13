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

import copy
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

# Carry rates are annualized decimals (0.10 = 10% per year). Using a fixed
# 365-day year keeps accrual deterministic across calendar boundaries.
SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0

# Quantity comparisons closer than this are treated as equal, so floating-point
# dust from proportional partial-close allocation cannot leave a ghost position.
QUANTITY_EPSILON = 1e-12

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
    # Accrued borrow (short) or funding (long) cost, settled into cash on close.
    carry_cost: float = 0.0
    last_accrual_at: datetime | None = None
    # Entry-order metadata. The position stores the filled quantity; these
    # fields preserve the requested size and the resulting IOC order status so
    # the repository can record a partial fill without a second order table.
    requested_quantity: float = 0.0
    entry_order_status: str = "filled"
    entry_order_reason: str = ""


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
    carry_cost: float = 0.0
    position_id: str = ""


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
    carry_cost: float = 0.0


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
        slippage_by_symbol: Mapping[str, float] | None = None,
        borrow_rate_pct: float = 0.0,
        funding_rate_pct: float = 0.0,
        borrow_rate_by_symbol: Mapping[str, float] | None = None,
        funding_rate_by_symbol: Mapping[str, float] | None = None,
        max_volume_participation_pct: float = 0.0,
    ) -> None:
        """Create a paper portfolio.

        ``commission_pct`` and ``slippage_pct`` are expressed as decimals
        (0.001 = 10 bps). They default to zero so direct unit tests can model
        frictionless fills; the application wires the configured defaults from
        ``configs.settings`` into its shared engine.

        ``slippage_by_symbol`` overrides the global ``slippage_pct`` for named
        symbols; symbols not in the mapping fall back to the global value.

        ``borrow_rate_pct`` and ``funding_rate_pct`` are annualized decimals
        (0.10 = 10% per year). Borrow accrues on short notional and funding on
        long notional. Both default to zero for frictionless unit tests; the
        application wires the configured defaults. Per-symbol maps override the
        global annual rate for the named symbol.

        ``max_volume_participation_pct`` caps a fill at that fraction of the
        supplied candle volume (0.10 = 10%). Zero disables the cap so direct
        unit tests and callers without volume data keep filling the full
        requested quantity. The application wires a non-zero default.
        """
        if not 0.0 <= commission_pct < 1.0:
            raise ValueError("commission_pct must be between 0 and 1")
        if not 0.0 <= slippage_pct < 1.0:
            raise ValueError("slippage_pct must be between 0 and 1")
        if not 0.0 <= borrow_rate_pct < 10.0:
            raise ValueError("borrow_rate_pct must be between 0 and 10")
        if not 0.0 <= funding_rate_pct < 10.0:
            raise ValueError("funding_rate_pct must be between 0 and 10")
        if not 0.0 <= max_volume_participation_pct <= 1.0:
            raise ValueError("max_volume_participation_pct must be between 0 and 1")

        self._initial_capital = max(initial_capital, 1000.0)
        self._cash: float = self._initial_capital
        self._commission_pct = commission_pct
        self._slippage_pct = slippage_pct
        self._slippage_by_symbol = self._normalize_slippage_by_symbol(slippage_by_symbol)
        self._borrow_rate_pct = borrow_rate_pct
        self._funding_rate_pct = funding_rate_pct
        self._borrow_rate_by_symbol = self._normalize_rate_by_symbol(borrow_rate_by_symbol, "borrow_rate_by_symbol")
        self._funding_rate_by_symbol = self._normalize_rate_by_symbol(funding_rate_by_symbol, "funding_rate_by_symbol")
        self._max_volume_participation_pct = max_volume_participation_pct
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
        volume: float | None = None,
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
            volume: Optional candle volume. When the engine has a non-zero
                volume-participation cap, the fill is limited to that fraction
                of this volume. ``None`` or a non-positive value means volume
                is unavailable and no liquidity cap is applied.

        Returns:
            Dict with keys ``accepted``, ``position_id``, ``reversal``,
            ``closed_trade``, ``requested_quantity``, ``filled_quantity``,
            ``unfilled_quantity``, ``order_status``, and ``reason``.
        """
        if side not in ("long", "short"):
            return {"accepted": False, "reason": "Side must be 'long' or 'short'"}
        if quantity <= 0:
            return {"accepted": False, "reason": "Quantity must be positive"}
        if entry_price <= 0:
            return {"accepted": False, "reason": "Entry price must be positive"}

        requested_quantity = quantity
        liquidity_capacity = self._liquidity_capacity(volume)
        result: dict[str, Any] = {
            "accepted": True,
            "position_id": None,
            "reversal": False,
            "closed_trade": None,
            "reason": "ok",
            "requested_quantity": requested_quantity,
            "filled_quantity": 0.0,
            "unfilled_quantity": requested_quantity,
            "order_status": "rejected",
        }

        # Check for existing position in the same symbol
        existing = self._find_position(symbol)

        if existing is not None and existing.side == side:
            # Same direction — ignore
            return {"accepted": False, "reason": f"Already in {side} position for {symbol}"}

        # Apply adverse slippage to the signal price before mutating anything.
        # A long pays up; a short receives less. This is the actual fill
        # recorded on the position. Per-symbol slippage overrides the global
        # rate when configured.
        slippage_pct = self._slippage_for(symbol)
        fill_price = entry_price * (1.0 + slippage_pct) if side == "long" else entry_price * (1.0 - slippage_pct)
        if fill_price <= 0:
            return {"accepted": False, "reason": "Invalid fill price after slippage"}

        # Reversals close first because the freed cash/margin determines the
        # new position's buying power. Keep a light rollback of the fields
        # close_position() touches so a rejected reversal cannot leave the
        # existing position silently closed.
        entry_at = self._utc_now()
        reversal_state: tuple[float, list[PaperPosition], int, int, dict[str, float]] | None = None
        if existing is not None:
            # Deep-copy the positions: closing the existing position accrues its
            # carry in place, so a shallow list would leak that mutation into a
            # restored snapshot when the new fill is rejected.
            reversal_state = (
                self._cash,
                copy.deepcopy(self._positions),
                len(self._closed_trades),
                len(self._equity_curve),
                dict(self._last_prices),
            )
            closed = self.close_position(existing.id, entry_price, exit_reason="signal", exit_at=entry_at)
            if closed is None:
                self._restore_reversal_state(reversal_state)
                return {"accepted": False, "reason": "Could not close existing position"}
            result["reversal"] = True
            result["closed_trade"] = self._trade_to_dict(closed)

        # Longs are limited by free cash and by equity not already reserved as
        # short margin. Shorts require 100% notional margin, so their notional
        # cannot exceed current free margin. Both budgets include commission.
        equity = self._compute_equity()
        margin_used = sum(pos.margin for pos in self._positions)
        free_margin = max(equity - margin_used, 0.0)
        buying_power = min(self._cash, free_margin) if side == "long" else free_margin
        max_affordable = max(buying_power, 0.0) / (fill_price * (1.0 + self._commission_pct))
        actual_quantity = min(requested_quantity, max_affordable)
        if liquidity_capacity is not None:
            actual_quantity = min(actual_quantity, liquidity_capacity)

        if actual_quantity <= QUANTITY_EPSILON:
            if reversal_state is not None:
                self._restore_reversal_state(reversal_state)
            reason = (
                "Insufficient liquidity"
                if liquidity_capacity is not None and liquidity_capacity <= max_affordable
                else "Insufficient cash"
            )
            result.update(
                accepted=False,
                reason=reason,
                filled_quantity=0.0,
                unfilled_quantity=requested_quantity,
                order_status="rejected",
                unfilled_reason=reason,
            )
            return result

        order_status = "filled" if actual_quantity >= requested_quantity - QUANTITY_EPSILON else "partially_filled"
        unfilled_reason = ""
        if order_status == "partially_filled":
            reasons: list[str] = []
            if liquidity_capacity is not None and liquidity_capacity <= max_affordable + QUANTITY_EPSILON:
                reasons.append("volume participation cap")
            cash_capacity = liquidity_capacity if liquidity_capacity is not None else math.inf
            if max_affordable <= cash_capacity + QUANTITY_EPSILON:
                reasons.append("insufficient buying power")
            reasons.append("unfilled remainder cancelled (IOC)")
            unfilled_reason = "; ".join(reasons)

        result["filled_quantity"] = actual_quantity
        result["unfilled_quantity"] = max(requested_quantity - actual_quantity, 0.0)
        result["order_status"] = order_status
        result["liquidity_capped"] = (
            liquidity_capacity is not None
            and actual_quantity >= liquidity_capacity - QUANTITY_EPSILON
            and liquidity_capacity < requested_quantity - QUANTITY_EPSILON
        )
        if unfilled_reason:
            result["unfilled_reason"] = unfilled_reason

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
            entry_at=entry_at,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_name=strategy_name,
            entry_commission=entry_commission,
            margin=margin,
            last_accrual_at=entry_at,
            requested_quantity=requested_quantity,
            entry_order_status=order_status,
            entry_order_reason=unfilled_reason,
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

    def _restore_reversal_state(
        self,
        state: tuple[float, list[PaperPosition], int, int, dict[str, float]],
    ) -> None:
        """Undo a provisional reversal close after the new fill is rejected."""
        cash, positions, closed_count, curve_count, last_prices = state
        self._cash = cash
        self._positions = positions
        del self._closed_trades[closed_count:]
        del self._equity_curve[curve_count:]
        self._last_prices = last_prices

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str = "signal",
        exit_at: datetime | None = None,
        quantity: float | None = None,
    ) -> ClosedTrade | None:
        """Close all or part of an open position and record the trade.

        Args:
            position_id: UUID of the position to close.
            exit_price: Reference price at which the position is exited;
                adverse slippage and commission are applied to the fill.
            exit_reason: Reason for closing (``"signal"``, ``"stop_loss"``,
                ``"take_profit"``).
            exit_at: Optional exit timestamp. Carry is accrued from the
                position's ``last_accrual_at`` to this time and settled into
                cash and PnL. Defaults to the current UTC time.
            quantity: Optional number of units to close. ``None`` or a value
                at least the position quantity closes the whole position.
                A smaller positive value realizes a partial close: the
                position keeps its remaining quantity, stop, take-profit, and
                accrual clock, and entry commission/carry are allocated
                proportionally.

        Returns:
            The ``ClosedTrade`` record for the closed quantity, or ``None`` if
            the position is not found or the requested quantity is invalid.
        """
        if exit_price <= 0:
            return None
        if quantity is not None and (not math.isfinite(quantity) or quantity <= 0):
            return None

        exit_time = self._normalize_utc(exit_at) if exit_at is not None else self._utc_now()

        for i, pos in enumerate(self._positions):
            if pos.id == position_id:
                # Accrue before removing the position so the final partial
                # period is charged exactly once.
                self._accrue_position(pos, exit_time)

                # Exit fills are adverse: a long sells lower; a short buys higher.
                # Use the position's symbol so entry and exit costs cannot drift
                # apart when a per-symbol override is configured.
                slippage_pct = self._slippage_for(pos.symbol)
                exit_fill = (
                    exit_price * (1.0 - slippage_pct) if pos.side == "long" else exit_price * (1.0 + slippage_pct)
                )
                if exit_fill <= 0:
                    # Keep the position rather than recording an invalid fill.
                    return None

                close_quantity = pos.quantity if quantity is None else min(quantity, pos.quantity)
                if close_quantity <= QUANTITY_EPSILON:
                    return None
                full_close = close_quantity >= pos.quantity - QUANTITY_EPSILON
                fraction = 1.0 if full_close else close_quantity / pos.quantity

                # Allocate cumulative entry commission and carry to the closed
                # quantity. The remaining position keeps the rest, so the sum of
                # closed trades plus open liability still reconciles with the
                # cash that was actually paid.
                carry_closed = pos.carry_cost * fraction
                entry_commission_closed = pos.entry_commission * fraction
                exit_value = close_quantity * exit_fill
                exit_commission = exit_value * self._commission_pct
                if pos.side == "long":
                    price_pnl = close_quantity * (exit_fill - pos.entry_price)
                    self._cash += exit_value - exit_commission - carry_closed
                else:
                    price_pnl = close_quantity * (pos.entry_price - exit_fill)
                    self._cash -= exit_value + exit_commission + carry_closed

                pnl = price_pnl - entry_commission_closed - exit_commission - carry_closed
                entry_value = close_quantity * pos.entry_price
                pnl_pct = (pnl / entry_value * 100.0) if entry_value > 0 else 0.0

                trade = ClosedTrade(
                    symbol=pos.symbol,
                    side=pos.side,
                    quantity=close_quantity,
                    entry_price=pos.entry_price,
                    exit_price=exit_fill,
                    entry_at=pos.entry_at,
                    exit_at=exit_time,
                    pnl=round(pnl, 2),
                    pnl_pct=round(pnl_pct, 4),
                    exit_reason=exit_reason,
                    strategy_name=pos.strategy_name,
                    entry_commission=entry_commission_closed,
                    exit_commission=exit_commission,
                    carry_cost=carry_closed,
                    position_id=pos.id,
                )
                self._closed_trades.append(trade)

                if full_close:
                    self._positions.pop(i)
                    self._last_prices.pop(pos.symbol, None)
                else:
                    pos.quantity -= close_quantity
                    pos.entry_commission -= entry_commission_closed
                    pos.carry_cost -= carry_closed
                    pos.margin = pos.quantity * pos.entry_price if pos.side == "short" else 0.0

                # Track equity after the position is removed or reduced.
                self._equity_curve.append(self._compute_equity())

                return trade

        return None

    def check_sl_tp(
        self,
        symbol: str,
        high: float,
        low: float,
        open_price: float | None = None,
        as_of: datetime | None = None,
        volume: float | None = None,
    ) -> list[ClosedTrade]:
        """Check open positions for a symbol against a candle's high/low/open for SL/TP.

        Args:
            symbol: Ticker symbol.
            high: Current candle's high price.
            low: Current candle's low price.
            open_price: Optional candle open. When the candle opens beyond the
                stop, the stop fills at the open instead of the stop level.
                ``None`` keeps the stop-level fill for callers that only have
                high/low data.
            as_of: Optional candle timestamp. Carry is accrued to this time
                before a position closes. ``None`` uses the current UTC time.
            volume: Optional candle volume. When the engine has a non-zero
                volume-participation cap, a triggered exit closes at most that
                fraction of this volume. The remainder stays open and is
                re-evaluated on the next candle. ``None`` or a non-positive
                value closes the full position.

        Returns:
            List of ``ClosedTrade`` records for the quantities that were
            stopped out or took profit.
        """
        closed: list[ClosedTrade] = []
        exit_time = self._normalize_utc(as_of) if as_of is not None else None
        # A non-positive open is unusable; fall back to the stop level rather
        # than recording an invalid fill.
        gap_open = open_price if open_price is not None and open_price > 0 else None
        liquidity_capacity = self._liquidity_capacity(volume)

        for pos in list(self._positions):
            if pos.symbol != symbol:
                continue

            exit_price: float | None = None
            reason: str | None = None

            # If a candle spans both levels, the intra-candle path is unknown.
            # Assume the adverse level was reached first; optimistic ordering
            # would inflate paper results and distort the promotion gate.
            # Take-profit always fills at its level, even on a favourable gap.
            if pos.side == "long":
                if pos.stop_loss is not None and low <= pos.stop_loss:
                    exit_price = pos.stop_loss
                    if gap_open is not None and gap_open <= pos.stop_loss:
                        exit_price = gap_open
                    reason = "stop_loss"
                elif pos.take_profit is not None and high >= pos.take_profit:
                    exit_price = pos.take_profit
                    reason = "take_profit"
            else:  # short
                if pos.stop_loss is not None and high >= pos.stop_loss:
                    exit_price = pos.stop_loss
                    if gap_open is not None and gap_open >= pos.stop_loss:
                        exit_price = gap_open
                    reason = "stop_loss"
                elif pos.take_profit is not None and low <= pos.take_profit:
                    exit_price = pos.take_profit
                    reason = "take_profit"

            if reason is not None and exit_price is not None:
                exit_quantity = pos.quantity if liquidity_capacity is None else min(pos.quantity, liquidity_capacity)
                if exit_quantity <= QUANTITY_EPSILON:
                    continue
                trade = self.close_position(
                    pos.id,
                    exit_price,
                    exit_reason=reason,
                    exit_at=exit_time,
                    quantity=exit_quantity,
                )
                if trade is not None:
                    closed.append(trade)

        return closed

    def mark_to_market(self, symbol: str, price: float, as_of: datetime | None = None) -> None:
        """Mark open positions for ``symbol`` at the latest market price.

        Carry is accrued for every open position up to ``as_of`` (or now), so a
        mark also captures the cost of holding. Appending the resulting equity
        to the curve is what makes intra-trade drawdown measurable. Calling
        this with a symbol that has no open position still accrues carry but
        does not append a duplicate curve point.
        """
        if price <= 0:
            return
        self.accrue_carry(as_of)
        if not any(pos.symbol == symbol for pos in self._positions):
            return
        self._last_prices[symbol] = price
        self._equity_curve.append(self._compute_equity())

    def accrue_carry(self, as_of: datetime | None = None) -> float:
        """Accrue borrow/funding on every open position up to ``as_of``.

        The charge is based on entry notional and elapsed time since each
        position's ``last_accrual_at``, so repeated calls with the same
        timestamp (or an older one) do not double-charge. A zero rate still
        advances the clock, which keeps later accruals from replaying the
        entire holding period. Returns the total cost accrued by this call.
        """
        when = self._normalize_utc(as_of) if as_of is not None else self._utc_now()
        return sum(self._accrue_position(pos, when) for pos in self._positions)

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
        carry_cost = sum(pos.carry_cost for pos in self._positions) + sum(t.carry_cost for t in self._closed_trades)

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
            carry_cost=round(carry_cost, 2),
        )

    # ------------------------------------------------------------------
    # Durable-ledger support
    # ------------------------------------------------------------------

    def get_open_positions(self) -> list[PaperPosition]:
        """Return a copy of the open-position list for persistence/read APIs."""
        return list(self._positions)

    def get_closed_trades(self) -> list[ClosedTrade]:
        """Return a copy of the closed-trade list for persistence/read APIs."""
        return list(self._closed_trades)

    def get_equity_curve(self) -> list[float]:
        """Return a copy of the equity curve (one point per mark/closure)."""
        return list(self._equity_curve)

    def get_last_prices(self) -> dict[str, float]:
        """Return a copy of the latest marks."""
        return dict(self._last_prices)

    def snapshot(self) -> dict[str, Any]:
        """Capture the mutable state needed to roll back a failed DB write."""
        return {
            "cash": self._cash,
            "positions": copy.deepcopy(self._positions),
            "closed_trades": copy.deepcopy(self._closed_trades),
            "equity_curve": list(self._equity_curve),
            "last_prices": dict(self._last_prices),
        }

    def restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Restore a snapshot produced by :meth:`snapshot`."""
        self.restore_state(
            cash=float(snapshot["cash"]),
            positions=snapshot["positions"],
            closed_trades=snapshot["closed_trades"],
            equity_curve=snapshot["equity_curve"],
            last_prices=snapshot["last_prices"],
        )

    def restore_state(
        self,
        *,
        cash: float,
        positions: list[PaperPosition],
        closed_trades: list[ClosedTrade],
        equity_curve: list[float],
        last_prices: dict[str, float] | None = None,
        initial_capital: float | None = None,
    ) -> None:
        """Hydrate an engine from a durable ledger snapshot.

        The constructor owns the initial capital; this method is the only
        supported way to replace the in-memory cache with persisted state.
        """
        if initial_capital is not None:
            self._initial_capital = max(float(initial_capital), 1000.0)
        self._cash = float(cash)
        self._positions = copy.deepcopy(positions)
        self._closed_trades = copy.deepcopy(closed_trades)
        self._last_prices = dict(last_prices or {})

        curve = [float(point) for point in equity_curve]
        if not curve:
            curve = [self._initial_capital]
        self._equity_curve = curve

        # Include the current mark in the drawdown series without creating a
        # duplicate point on every process refresh.
        current_equity = self._compute_equity()
        if not math.isclose(self._equity_curve[-1], current_equity, rel_tol=1e-9, abs_tol=0.01):
            self._equity_curve.append(current_equity)

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

    @staticmethod
    def _normalize_slippage_by_symbol(mapping: Mapping[str, float] | None) -> dict[str, float]:
        """Validate and case-normalize per-symbol slippage overrides."""
        normalized: dict[str, float] = {}
        for raw_symbol, raw_pct in (mapping or {}).items():
            symbol = str(raw_symbol).strip().upper()
            if not symbol:
                raise ValueError("slippage_by_symbol keys must be non-empty symbols")
            pct = float(raw_pct)
            if not 0.0 <= pct < 1.0:
                raise ValueError(f"slippage_by_symbol[{raw_symbol!r}] must be between 0 and 1")
            normalized[symbol] = pct
        return normalized

    def _slippage_for(self, symbol: str) -> float:
        """Return the symbol override or the global slippage rate."""
        return self._slippage_by_symbol.get(symbol.upper(), self._slippage_pct)

    @staticmethod
    def _normalize_rate_by_symbol(mapping: Mapping[str, float] | None, label: str) -> dict[str, float]:
        """Validate and case-normalize per-symbol annual carry rates."""
        normalized: dict[str, float] = {}
        for raw_symbol, raw_rate in (mapping or {}).items():
            symbol = str(raw_symbol).strip().upper()
            if not symbol:
                raise ValueError(f"{label} keys must be non-empty symbols")
            rate = float(raw_rate)
            if not 0.0 <= rate < 10.0:
                raise ValueError(f"{label}[{raw_symbol!r}] must be between 0 and 10")
            normalized[symbol] = rate
        return normalized

    def _carry_rate_for(self, symbol: str, side: str) -> float:
        """Return the annualized borrow (short) or funding (long) rate."""
        if side == "short":
            return self._borrow_rate_by_symbol.get(symbol.upper(), self._borrow_rate_pct)
        return self._funding_rate_by_symbol.get(symbol.upper(), self._funding_rate_pct)

    def _liquidity_capacity(self, volume: float | None) -> float | None:
        """Return the maximum fill quantity implied by candle volume.

        ``None`` means the cap is disabled or volume is unavailable. A
        non-positive volume is treated as unknown rather than zero liquidity:
        some data sources (for example CoinGecko) report no volume, and
        rejecting every fill in that case would halt paper trading.
        """
        if self._max_volume_participation_pct <= 0.0:
            return None
        if volume is None or not math.isfinite(volume) or volume <= 0.0:
            return None
        return float(volume) * self._max_volume_participation_pct

    @staticmethod
    def _normalize_utc(value: datetime) -> datetime:
        """Normalize a timestamp to aware UTC; naive values are assumed UTC."""
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(UTC)

    def _accrue_position(self, position: PaperPosition, as_of: datetime) -> float:
        """Accrue one position's carry up to ``as_of`` and return the delta."""
        last = self._normalize_utc(position.last_accrual_at or position.entry_at)
        if as_of <= last:
            return 0.0
        elapsed_seconds = (as_of - last).total_seconds()
        notional = position.quantity * position.entry_price
        cost = notional * self._carry_rate_for(position.symbol, position.side) * elapsed_seconds / SECONDS_PER_YEAR
        position.carry_cost += cost
        position.last_accrual_at = as_of
        return cost

    def _compute_equity(self) -> float:
        """Compute total portfolio equity at the latest marks.

        Longs add market value to cash. Shorts subtract their liability, while
        their credited proceeds remain in cash. Accrued carry is a liability
        until the position closes, so it is subtracted here and settled into
        cash by :meth:`close_position`. At entry this reduces equity by the
        entry commission only, which is the correct accounting identity.
        """
        equity = self._cash - sum(pos.carry_cost for pos in self._positions)
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
            "carry_cost": round(trade.carry_cost, 8),
            "fees": round(trade.entry_commission + trade.exit_commission, 2),
        }
