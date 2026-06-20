"""Trading API router — portfolio, positions, orders, and execution.

Endpoints:
    GET  /api/v1/portfolio  — Portfolio summary (PnL, win rate, drawdown)
    GET  /api/v1/positions   — Current open positions
    GET  /api/v1/orders      — Closed trade history
    POST /api/v1/execute     — Execute a trade signal
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from configs.settings import settings
from paper_trading.engine import PaperTradingEngine

router = APIRouter(prefix="/api/v1", tags=["trading"])

# Singleton paper trading engine shared across requests
_engine: PaperTradingEngine | None = None


def _get_engine() -> PaperTradingEngine:
    """Get or create the paper trading engine singleton."""
    global _engine  # noqa: PLW0603
    if _engine is None:
        _engine = PaperTradingEngine(
            initial_capital=settings.paper_trading_initial_capital,
        )
    return _engine


@router.get("/portfolio")
async def portfolio() -> dict[str, Any]:
    """Get the paper trading portfolio summary."""
    engine = _get_engine()
    summary = engine.get_summary()
    return {
        "initial_capital": summary.initial_capital,
        "cash": summary.cash,
        "total_pnl": summary.total_pnl,
        "total_return_pct": summary.total_return_pct,
        "win_rate": summary.win_rate,
        "total_trades": summary.total_trades,
        "winning_trades": summary.winning_trades,
        "losing_trades": summary.losing_trades,
        "open_positions": summary.open_positions,
        "max_drawdown_pct": summary.max_drawdown_pct,
    }


@router.get("/positions")
async def positions() -> list[dict[str, Any]]:
    """Get all open positions."""
    engine = _get_engine()
    # Access internal _positions via public method if available
    return _get_open_positions(engine)


def _get_open_positions(engine: PaperTradingEngine) -> list[dict[str, Any]]:
    """Extract open positions as dicts."""
    # Use a safe approach — check private list directly
    positions_list: list[dict[str, Any]] = []
    # Access via the internal _positions list (no public getter)
    for pos in engine._positions:  # noqa: SLF001
        positions_list.append({
            "id": pos.id,
            "symbol": pos.symbol,
            "side": pos.side,
            "quantity": pos.quantity,
            "entry_price": pos.entry_price,
            "entry_at": pos.entry_at.isoformat()
            if hasattr(pos.entry_at, "isoformat")
            else str(pos.entry_at),
            "stop_loss": pos.stop_loss,
            "take_profit": pos.take_profit,
            "strategy_name": pos.strategy_name,
        })
    return positions_list


@router.get("/orders")
async def orders() -> list[dict[str, Any]]:
    """Get closed trade history (most recent first)."""
    engine = _get_engine()
    return [_trade_to_dict(t) for t in reversed(engine._closed_trades)]  # noqa: SLF001


@router.post("/execute")
async def execute(body: dict[str, Any]) -> dict[str, Any]:
    """Execute a trade signal on the paper trading engine.

    Body:
        symbol (str): Ticker symbol
        side (str): "long" or "short"
        quantity (float): Number of units
        entry_price (float): Price per unit
        stop_loss (float, optional): Stop-loss level
        take_profit (float, optional): Take-profit level
        strategy_name (str, optional): Strategy name
    """
    engine = _get_engine()

    symbol = body.get("symbol", "")
    side = body.get("side", "long")
    quantity = float(body.get("quantity", 0))
    entry_price = float(body.get("entry_price", 0))

    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")
    if side not in ("long", "short"):
        raise HTTPException(status_code=400, detail="side must be 'long' or 'short'")
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")
    if entry_price <= 0:
        raise HTTPException(status_code=400, detail="entry_price must be positive")

    stop_loss = body.get("stop_loss")
    take_profit = body.get("take_profit")

    result = engine.execute_signal(
        symbol=symbol,
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        stop_loss=float(stop_loss) if stop_loss is not None else None,
        take_profit=float(take_profit) if take_profit is not None else None,
        strategy_name=body.get("strategy_name", ""),
    )

    return result  # type: ignore[return-value]


def _trade_to_dict(trade: Any) -> dict[str, Any]:
    """Convert a ClosedTrade to a JSON-serializable dict."""
    return {
        "symbol": trade.symbol,
        "side": trade.side,
        "quantity": trade.quantity,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "entry_at": trade.entry_at.isoformat()
        if hasattr(trade.entry_at, "isoformat")
        else str(trade.entry_at),
        "exit_at": trade.exit_at.isoformat()
        if hasattr(trade.exit_at, "isoformat")
        else str(trade.exit_at),
        "pnl": trade.pnl,
        "pnl_pct": trade.pnl_pct,
        "exit_reason": trade.exit_reason,
        "strategy_name": trade.strategy_name,
    }
