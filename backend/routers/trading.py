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

import math
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from agents.consensus import ConsensusEngine
from agents.risk import MAX_POSITION_SIZE_PCT, MAX_RISK_SCORE
from backend.core.dependencies import require_trading_access
from backend.schemas.trading import ExecuteTradeRequest
from configs.settings import settings
from database.connection import async_session_factory
from paper_trading.engine import ClosedTrade, PaperPosition, PaperTradingEngine
from paper_trading.ledger import PaperTradingLedger
from paper_trading.repository import (
    PaperLedgerBusyError,
    PaperLedgerError,
    PaperLedgerRepository,
    PaperOrderConflictError,
)

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
            writer_timeout_seconds=settings.paper_trading_writer_lock_timeout_seconds,
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


@router.post("/execute", dependencies=[Depends(require_trading_access)])
async def execute(payload: ExecuteTradeRequest) -> dict[str, Any]:
    """Execute a paper trade only when the upstream agents approved it.

    The request carries the Market Analyst, Quant, and Risk outputs. The
    server re-runs the deterministic consensus gate, verifies Risk's approval
    and sizing, derives the fill price from the approved market snapshot, and
    caps notional exposure at the 2% risk limit. There is no manual bypass in
    this endpoint; use the normal ``/signal`` pipeline for generated trades.

    ``client_order_id`` is idempotent per paper account. A duplicate returns
    **409** and never creates a second position.
    """
    ledger = get_paper_trading_ledger()
    approval = payload.approval
    market = approval.market_analyst_output
    quant = approval.quant_output
    risk = approval.risk_output

    if market.direction != payload.side or quant.direction != payload.side:
        raise HTTPException(
            status_code=422,
            detail="Approval direction does not match the requested side",
        )

    consensus = ConsensusEngine.evaluate(
        payload.symbol,
        market.model_dump(),
        quant.model_dump(),
        vision_output=approval.vision_output.model_dump() if approval.vision_output else None,
    )
    if not consensus["approved"]:
        raise HTTPException(status_code=422, detail=str(consensus["rationale"]))

    if not risk.approved:
        reasons = "; ".join(risk.reasons) if risk.reasons else "Risk Agent rejected trade"
        raise HTTPException(status_code=422, detail=reasons)
    if not math.isfinite(risk.risk_score) or risk.risk_score > MAX_RISK_SCORE:
        raise HTTPException(
            status_code=422,
            detail=f"Risk score {risk.risk_score:.1f} exceeds the maximum {MAX_RISK_SCORE:.0f}",
        )

    current_price = market.indicators.get("current_price")
    try:
        entry_price = float(current_price) if current_price is not None else 0.0
    except (TypeError, ValueError):
        entry_price = 0.0
    if not math.isfinite(entry_price) or entry_price <= 0:
        raise HTTPException(
            status_code=422,
            detail="Approved Market Analyst output has no valid current_price",
        )

    try:
        quantity = float(risk.max_position_size) if risk.max_position_size is not None else 0.0
    except (TypeError, ValueError):
        quantity = 0.0
    if not math.isfinite(quantity) or quantity <= 0:
        raise HTTPException(
            status_code=422,
            detail="Approved Risk output has no valid max_position_size",
        )

    stop_loss = risk.stop_loss
    if stop_loss is not None:
        if not math.isfinite(stop_loss) or stop_loss <= 0:
            raise HTTPException(status_code=422, detail="Approved stop_loss must be positive")
        if payload.side == "long" and stop_loss >= entry_price:
            raise HTTPException(status_code=422, detail="Long stop_loss must be below the entry price")
        if payload.side == "short" and stop_loss <= entry_price:
            raise HTTPException(status_code=422, detail="Short stop_loss must be above the entry price")

    try:
        summary = await ledger.get_summary()
    except PaperLedgerError as exc:
        raise HTTPException(status_code=503, detail="Paper ledger unavailable") from exc

    max_notional = summary.equity * (MAX_POSITION_SIZE_PCT / 100.0)
    notional = quantity * entry_price
    if (
        not math.isfinite(summary.equity)
        or summary.equity <= 0
        or not math.isfinite(notional)
        or notional > max_notional * 1.001
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Approved size {notional:.2f} exceeds the "
                f"{MAX_POSITION_SIZE_PCT:.0f}% paper-account limit ({max_notional:.2f})"
            ),
        )

    try:
        result = await ledger.execute_signal(
            symbol=payload.symbol,
            side=payload.side,
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=None,
            strategy_name=quant.strategy_name or market.setup or "consensus",
            client_order_id=payload.client_order_id,
        )
    except PaperOrderConflictError as exc:
        raise HTTPException(status_code=409, detail="client_order_id has already been used") from exc
    except PaperLedgerBusyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Paper ledger is busy; retry shortly",
            headers={"Retry-After": "1"},
        ) from exc
    except PaperLedgerError as exc:
        raise HTTPException(status_code=503, detail="Paper ledger unavailable") from exc

    result["client_order_id"] = payload.client_order_id
    return result


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
