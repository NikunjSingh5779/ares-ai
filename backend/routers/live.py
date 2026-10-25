"""Live trading API router.

Provides endpoints for engine control, safety gate management,
position/order viewing, and audit log access.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.core.dependencies import require_live_control
from configs.settings import settings
from database.connection import async_session_factory
from live_trading import (
    KillSwitch,
    LiveTradingEngine,
    ModeManager,
    PromotionGate,
    TradingMode,
)
from live_trading.audit import OrderAuditor
from live_trading.exchange import create_exchange
from live_trading.safety import create_kill_switch_redis

logger = logging.getLogger("ares")

router = APIRouter(prefix="/api/v1/live", tags=["live"])


# ── Request models ───────────────────────────────────────────────────────────


class SetModeRequest(BaseModel):
    mode: str


class KillSwitchRequest(BaseModel):
    reason: str = "manual"


# ── Lazy singleton ──────────────────────────────────────────────────────────

_engine: LiveTradingEngine | None = None
_kill_switch: KillSwitch | None = None


def _get_kill_switch() -> KillSwitch:
    """Return the process-wide kill switch, backed by shared Redis state.

    The switch is available even when no exchange is configured, so an
    operator can always halt future live order placement.  Redis failures
    latch it closed (see ``KillSwitch``).
    """
    global _kill_switch
    if _kill_switch is None:
        _kill_switch = KillSwitch(
            max_drawdown_pct=settings.live_max_drawdown_pct,
            redis_client=create_kill_switch_redis(),
        )
    return _kill_switch


def _get_engine() -> LiveTradingEngine | None:
    """Get or create the live trading engine singleton.

    Returns ``None`` when the exchange connector cannot be created
    (e.g. missing ``ccxt`` library or empty API keys).  Callers must
    handle the ``None`` case gracefully.
    """
    global _engine
    if _engine is not None:
        return _engine

    kill_switch = _get_kill_switch()
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
    engine = LiveTradingEngine(
        exchange,
        kill_switch,
        mode_manager,
        promotion_gate,
        auditor=auditor,
        session_factory=async_session_factory,
    )
    _engine = engine
    logger.info("Live trading engine created (lazy singleton)")
    return engine


# ── DTOs ────────────────────────────────────────────────────────────────────


class _LiveStatusResponse(dict[str, Any]):
    """Response model for /status endpoint."""


def _not_configured_status() -> dict[str, Any]:
    """Status payload when no exchange connector can be created.

    The kill switch is still real: it reads shared Redis state so the UI can
    report an active trip even in paper-only mode.
    """
    ks = _get_kill_switch()
    return {
        "running": False,
        "connected": False,
        "mode": "paper",
        "live_trading_enabled": settings.live_trading_enabled,
        "kill_switch": {
            "active": ks.is_active,
            "triggered_by": ks.triggered_by,
            "triggered_at": ks.triggered_at.isoformat() if ks.triggered_at else None,
            "max_drawdown_pct": ks.max_drawdown_pct,
            "storage_healthy": ks.storage_healthy,
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
        "Set exchange API keys in .env and LIVE_TRADING_ENABLED=true to enable live trading.",
    }


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/status")
async def live_status() -> dict[str, Any]:
    """Return engine state: mode, kill switch, connection, paper record."""
    engine = _get_engine()
    if engine is None:
        return _not_configured_status()
    ks = engine.kill_switch
    pr = await engine.paper_record()
    return {
        "running": engine.is_running,
        "connected": engine.is_connected,
        "mode": engine.mode.value,
        "live_trading_enabled": settings.live_trading_enabled,
        "kill_switch": {
            "active": ks.is_active,
            "triggered_by": ks.triggered_by,
            "triggered_at": ks.triggered_at.isoformat() if ks.triggered_at else None,
            "max_drawdown_pct": ks.max_drawdown_pct,
            "storage_healthy": ks.storage_healthy,
        },
        "exchange": engine.exchange.exchange_name,
        "paper_record": pr,
    }


_NO_ENGINE_MSG = "Exchange not configured. Set API keys in .env first."


@router.post("/mode", dependencies=[Depends(require_live_control)])
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

    if new_mode in (TradingMode.AUTO, TradingMode.SEMI) and not settings.live_trading_enabled:
        raise HTTPException(
            status_code=403,
            detail=(
                "Live trading is disabled (paper-only mode). Set "
                "LIVE_TRADING_ENABLED=true explicitly before selecting "
                f"{new_mode.value} mode."
            ),
        )

    # Block AUTO and SEMI modes if promotion gate not passed
    if new_mode in (TradingMode.AUTO, TradingMode.SEMI):
        pr = await engine.paper_record()
        promo = pr["promotion"]
        if not promo["passed"]:
            detail = (
                f"Cannot switch to {new_mode.value} mode — paper record insufficient: "
                f"{promo['trades']['current']}/{promo['trades']['required']} trades, "
                f"{promo['days']['current']}/{promo['days']['required']} days"
            )
            risk = promo.get("risk", {})
            if risk.get("max_drawdown_pct") is not None and risk["max_drawdown_pct"] > risk.get(
                "max_drawdown_allowed_pct", float("inf")
            ):
                detail += (
                    f"; max drawdown {risk['max_drawdown_pct']:.1f}% exceeds allowed "
                    f"{risk['max_drawdown_allowed_pct']:.1f}%"
                )
            if risk.get("total_pnl") is not None and risk["total_pnl"] < 0:
                detail += f"; paper record is net-losing (${risk['total_pnl']:,.2f})"
            raise HTTPException(status_code=400, detail=detail)

    engine.mode_manager.set_mode(new_mode)
    logger.info("Trading mode changed to %s", new_mode.value)
    return {"mode": new_mode.value}


@router.post("/start", dependencies=[Depends(require_live_control)])
async def start_engine() -> dict[str, Any]:
    """Connect to the exchange and start the live engine."""
    if not settings.live_trading_enabled:
        raise HTTPException(
            status_code=403,
            detail=(
                "Live trading is disabled (paper-only mode). Set "
                "LIVE_TRADING_ENABLED=true explicitly to allow live execution."
            ),
        )
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


@router.post("/stop", dependencies=[Depends(require_live_control)])
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


@router.post("/kill", dependencies=[Depends(require_live_control)])
async def activate_kill_switch(body: KillSwitchRequest) -> dict[str, Any]:
    """Activate the kill switch — halts all live order placement immediately.

    Works even when no exchange is configured. If the shared Redis store is
    unavailable the switch still latches closed locally; ``shared`` reports
    whether the trip was written to Redis.
    """
    ks = _get_kill_switch()
    shared = ks.activate(reason=body.reason)
    logger.warning("Kill switch activated: %s (shared=%s)", body.reason, shared)
    response: dict[str, Any] = {
        "status": "kill_switch_active",
        "triggered_by": body.reason,
        "active": ks.is_active,
        "shared": shared,
    }
    if not shared:
        response["warning"] = (
            "Kill switch state store unavailable — the switch is latched closed "
            "locally and every process fails closed until a human re-arms."
        )
    return response


@router.post("/arm", dependencies=[Depends(require_live_control)])
async def arm_kill_switch() -> dict[str, Any]:
    """Re-arm the kill switch — human confirmation required.

    Refuses to clear the latch when the shared store is unavailable, because
    that would silently re-enable trading.
    """
    ks = _get_kill_switch()
    if not ks.arm():
        raise HTTPException(
            status_code=503,
            detail=(
                "Cannot re-arm: kill switch state store is unavailable. "
                "Live orders remain blocked until the store recovers."
            ),
        )
    logger.info("Kill switch re-armed")
    return {"status": "kill_switch_armed", "active": False}


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


@router.get("/paper_record")
async def paper_record(
    account_id: str | None = Query(None, description="Filter by account UUID"),
    strategy_name: str | None = Query(None, description="Filter by strategy name"),
) -> dict[str, Any]:
    """Return paper trading stats for promotion check.

    By default aggregates across all paper accounts. Pass ``account_id``
    and/or ``strategy_name`` to scope the query to a specific account or
    strategy.

    Delegates to ``engine.paper_record()`` for the DB query, matching the
    router's pattern of keeping DB access behind the engine layer.
    """
    engine = _get_engine()
    if engine is None:
        return _not_configured_status()["paper_record"]  # type: ignore[no-any-return]

    try:
        return await engine.paper_record(account_id=account_id, strategy_name=strategy_name)
    except Exception as e:
        logger.error(f"Failed to query paper_record from DB: {e}")
        raise HTTPException(status_code=500, detail="Failed to query paper trading record from database")
