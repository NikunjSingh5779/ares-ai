"""Live trading API router.

Provides endpoints for engine control, safety gate management,
position/order viewing, and audit log access.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from live_trading import (
    KillSwitch,
    LiveTradingEngine,
    ModeManager,
    PromotionGate,
    TradingMode,
)
from live_trading.exchange import create_exchange
from live_trading.audit import OrderAuditor

logger = logging.getLogger("ares")

router = APIRouter(prefix="/api/v1/live", tags=["live"])


# ── Request models ───────────────────────────────────────────────────────────


class SetModeRequest(BaseModel):
    mode: str


class KillSwitchRequest(BaseModel):
    reason: str = "manual"


# ── Lazy singleton ──────────────────────────────────────────────────────────

_engine: LiveTradingEngine | None = None


def _get_engine() -> LiveTradingEngine | None:
    """Get or create the live trading engine singleton.

    Returns ``None`` when the exchange connector cannot be created
    (e.g. missing ``ccxt`` library or empty API keys).  Callers must
    handle the ``None`` case gracefully.
    """
    global _engine
    if _engine is not None:
        return _engine

    from configs.settings import settings

    kill_switch = KillSwitch(max_drawdown_pct=settings.live_max_drawdown_pct)
    mode_manager = ModeManager()
    promotion_gate = PromotionGate(
        min_paper_trades=settings.minimum_paper_trades,
        min_paper_days=settings.minimum_paper_days,
    )

    try:
        exchange_config = {
            "api_key": settings.exchange_api_key,
            "secret": settings.exchange_secret_key,
            "testnet": settings.exchange_testnet,
        }
        exchange = create_exchange(settings.exchange_name, config=exchange_config)
    except (ImportError, ValueError) as exc:
        logger.warning(
            "Exchange connector unavailable (%s): %s — live trading disabled",
            type(exc).__name__,
            exc,
        )
        return None

    auditor = OrderAuditor()
    engine = LiveTradingEngine(exchange, kill_switch, mode_manager, promotion_gate, auditor)
    _engine = engine
    logger.info("Live trading engine created (lazy singleton)")
    return engine


# ── DTOs ────────────────────────────────────────────────────────────────────


class _LiveStatusResponse(dict[str, Any]):
    """Response model for /status endpoint."""


_NOT_CONFIGURED_STATUS: dict[str, Any] = {
    "running": False,
    "connected": False,
    "mode": "paper",
    "kill_switch": {
        "active": False,
        "triggered_by": None,
        "triggered_at": None,
        "max_drawdown_pct": 20.0,
    },
    "exchange": "not_configured",
    "paper_record": {
        "promotion": {
            "passed": False,
            "trades": {"current": 0, "required": 50},
            "days": {"current": 0, "required": 30},
        }
    },
    "message": "No exchange configured. Running in paper trading mode. "
    "Set exchange API keys in .env to enable live trading.",
}


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/status")
async def live_status() -> dict[str, Any]:
    """Return engine state: mode, kill switch, connection, paper record."""
    engine = _get_engine()
    if engine is None:
        return _NOT_CONFIGURED_STATUS
    ks = engine.kill_switch
    return {
        "running": engine.is_running,
        "connected": engine.is_connected,
        "mode": engine.mode.value,
        "kill_switch": {
            "active": ks.is_active,
            "triggered_by": ks.triggered_by,
            "triggered_at": ks.triggered_at.isoformat() if ks.triggered_at else None,
            "max_drawdown_pct": ks.max_drawdown_pct,
        },
        "exchange": engine.exchange.exchange_name,
        "paper_record": engine.paper_record,
    }


_NO_ENGINE_MSG = "Exchange not configured. Set API keys in .env first."


@router.post("/mode")
async def set_mode(body: SetModeRequest) -> dict[str, Any]:
    """Change the trading mode.

    Blocked if kill switch is active or promotion gate hasn't passed.
    AUTO and SEMI modes require promotion gate to pass.
    """
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail=_NO_ENGINE_MSG)

    if engine.kill_switch.is_active:
        raise HTTPException(
            status_code=400,
            detail="Cannot change mode while kill switch is active. Arm the kill switch first.",
        )

    try:
        new_mode = TradingMode(body.mode)
    except ValueError:
        valid = [m.value for m in TradingMode]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{body.mode}'. Valid modes: {valid}",
        )

    # Block AUTO and SEMI modes if promotion gate not passed
    if new_mode in (TradingMode.AUTO, TradingMode.SEMI):
        promo = engine.paper_record["promotion"]
        if not promo["passed"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot switch to {new_mode.value} mode — paper record insufficient: "
                f"{promo['trades']['current']}/{promo['trades']['required']} trades, "
                f"{promo['days']['current']}/{promo['days']['required']} days",
            )

    engine.mode_manager.set_mode(new_mode)
    logger.info("Trading mode changed to %s", new_mode.value)
    return {"mode": new_mode.value}


@router.post("/start")
async def start_engine() -> dict[str, Any]:
    """Connect to the exchange and start the live engine."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail=_NO_ENGINE_MSG)
    if engine.is_running:
        return {"status": "already_running", "connected": engine.is_connected}

    success = await engine.start()
    if success:
        logger.info("Live trading engine started")
        return {"status": "started", "connected": True}
    raise HTTPException(status_code=500, detail="Failed to connect to exchange")


@router.post("/stop")
async def stop_engine() -> dict[str, Any]:
    """Disconnect from the exchange and stop the engine."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail=_NO_ENGINE_MSG)
    if not engine.is_running:
        return {"status": "already_stopped"}
    await engine.stop()
    logger.info("Live trading engine stopped")
    return {"status": "stopped"}


@router.post("/kill")
async def activate_kill_switch(body: KillSwitchRequest) -> dict[str, Any]:
    """Activate the kill switch — halts all live order placement immediately."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail=_NO_ENGINE_MSG)
    engine.kill_switch.activate(reason=body.reason)
    logger.warning("Kill switch activated: %s", body.reason)
    return {"status": "kill_switch_active", "triggered_by": body.reason}


@router.post("/arm")
async def arm_kill_switch() -> dict[str, Any]:
    """Re-arm the kill switch — human confirmation required."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail=_NO_ENGINE_MSG)
    engine.kill_switch.arm()
    logger.info("Kill switch re-armed")
    return {"status": "kill_switch_armed"}


@router.get("/positions")
async def live_positions() -> list[dict[str, Any]]:
    """Return live open positions (stub — returns empty list for non-futures exchanges)."""
    return []


@router.get("/orders")
async def live_orders() -> list[dict[str, Any]]:
    """Return live order history from the audit log."""
    engine = _get_engine()
    if engine is None:
        return []
    return engine.auditor.to_dicts(limit=50)


@router.get("/audit")
async def audit_log(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent audit log entries."""
    engine = _get_engine()
    if engine is None:
        return []
    return engine.auditor.to_dicts(limit=min(limit, 500))


from database.connection import async_session_factory
from sqlalchemy import text

@router.get("/paper_record")
async def paper_record() -> dict[str, Any]:
    """Return paper trading stats for promotion check."""
    engine = _get_engine()
    if engine is None:
        return _NOT_CONFIGURED_STATUS["paper_record"]
        
    try:
        async with async_session_factory() as session:
            # Query number of closed paper trades
            trades_count = (await session.execute(text("""
                SELECT COUNT(*) FROM trade_history th
                JOIN accounts a ON th.account_id = a.id
                WHERE a.exchange = 'paper' AND th.is_closed = true
            """))).scalar() or 0

            # Query number of unique trading days
            days_count = (await session.execute(text("""
                SELECT COUNT(DISTINCT DATE(entry_at)) FROM trade_history th
                JOIN accounts a ON th.account_id = a.id
                WHERE a.exchange = 'paper'
            """))).scalar() or 0
            
            # Pass these database metrics into the promotion gate
            return {
                "trades": trades_count,
                "days": days_count,
                "promotion": engine.promotion_gate.progress(trades_count, days_count)
            }
    except Exception as e:
        logger.error(f"Failed to query paper_record from DB: {e}")
        return engine.paper_record
