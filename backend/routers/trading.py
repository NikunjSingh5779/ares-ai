"""Trading API router — portfolio, positions, orders, and execution.

Endpoints:
    GET  /api/v1/portfolio  — Portfolio summary (PnL, win rate, drawdown)
    GET  /api/v1/positions  — Current open positions
    GET  /api/v1/orders     — Closed trade history
    POST /api/v1/execute    — Execute a paper trade signal

Reads are hydrated from the durable paper ledger before they are returned.
The in-memory engine is a calculation cache, not a second source of truth.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from configs.settings import settings
from database.connection import async_session_factory
from paper_trading.engine import ClosedTrade, PaperPosition, PaperTradingEngine
from paper_trading.ledger import PaperTradingLedger
from paper_trading.repository import PaperLedgerError, PaperLedgerRepository

router = APIRouter(prefix="/api/v1", tags=["trading"])

# Process-local calculation cache. Durable state lives in PostgreSQL and is
# loaded into this engine before every read/write through PaperTradingLedger.
_engine: PaperTradingEngine | None = None
_ledger: PaperTradingLedger | None = None


def get_paper_trading_ledger() -> PaperTradingLedger:
    """Get or create the process paper-trading service."""
    global _engine, _ledger  # noqa: PLW0603
    if _ledger is None:
        _engine = PaperTradingEngine(
            initial_capital=settings.paper_trading_initial_capital,
            commission_pct=settings.paper_trading_commission_pct,
            slippage_pct=settings.paper_trading_slippage_pct,
        )
        _ledger = PaperTradingLedger(
            engine=_engine,
            repository=PaperLedgerRepository(async_session_factory),
        )
    return _ledger


def _get_engine() -> PaperTradingEngine:
    """Return the shared paper engine cache (used by the runner/agents)."""
    return get_paper_trading_ledger().engine


@router.get("/portfolio")
async def portfolio() -> dict[str, Any]:
    """Get the paper trading portfolio summary from the durable ledger."""
    ledger = get_paper_trading_ledger()
    try:
        summary = await ledger.get_summary()
    except PaperLedgerError as exc:
        raise HTTPException(status_code=503, detail="Paper ledger unavailable") from exc
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
        "equity": summary.equity,
        "margin_used": summary.margin_used,
    }


@router.get("/positions")
async def positions() -> list[dict[str, Any]]:
    """Get all open positions from the durable ledger."""
    ledger = get_paper_trading_ledger()
    try:
        open_positions = await ledger.get_open_positions()
    except PaperLedgerError as exc:
        raise HTTPException(status_code=503, detail="Paper ledger unavailable") from exc
    return [_position_to_dict(position) for position in open_positions]


@router.get("/orders")
async def orders() -> list[dict[str, Any]]:
    """Get closed trade history (most recent first) from the durable ledger."""
    ledger = get_paper_trading_ledger()
    try:
        closed = await ledger.get_closed_trades()
    except PaperLedgerError as exc:
        raise HTTPException(status_code=503, detail="Paper ledger unavailable") from exc
    return [_trade_to_dict(trade) for trade in reversed(closed)]


@router.post("/execute")
async def execute(body: dict[str, Any]) -> dict[str, Any]:
    """Execute a paper trade signal and persist it atomically.

    Body:
        symbol (str): Ticker symbol
        side (str): "long" or "short"
        quantity (float): Number of units
        entry_price (float): Price per unit
        stop_loss (float, optional): Stop-loss level
        take_profit (float, optional): Take-profit level
        strategy_name (str, optional): Strategy name
    """
    ledger = get_paper_trading_ledger()

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

    try:
        return await ledger.execute_signal(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=float(stop_loss) if stop_loss is not None else None,
            take_profit=float(take_profit) if take_profit is not None else None,
            strategy_name=body.get("strategy_name", ""),
        )
    except PaperLedgerError as exc:
        raise HTTPException(status_code=503, detail="Paper ledger unavailable") from exc


def _position_to_dict(position: PaperPosition) -> dict[str, Any]:
    """Convert an engine position to a JSON-serializable dict."""
    return {
        "id": position.id,
        "symbol": position.symbol,
        "side": position.side,
        "quantity": position.quantity,
        "entry_price": position.entry_price,
        "entry_at": position.entry_at.isoformat()
        if hasattr(position.entry_at, "isoformat")
        else str(position.entry_at),
        "stop_loss": position.stop_loss,
        "take_profit": position.take_profit,
        "strategy_name": position.strategy_name,
        "entry_commission": position.entry_commission,
        "margin": position.margin,
    }


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
