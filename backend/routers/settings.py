"""Settings API router.

Endpoints:
    GET /api/v1/settings             — effective safety limits + preferences
    PUT /api/v1/settings/preferences — persist dashboard preferences

The safety block is read-only and comes from the same constants the trading and
live paths use. This router can never raise a position cap, risk ceiling,
confidence threshold, drawdown limit, or promotion gate.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agents.consensus import REQUIRED_CONFIDENCE
from agents.risk import MAX_POSITION_SIZE_PCT, MAX_RISK_SCORE
from backend.core.dependencies import get_db
from backend.schemas.settings import DashboardPreferences, SafetyLimits, SettingsResponse
from backend.services import settings_service
from configs.settings import settings

logger = logging.getLogger("ares.api.settings")

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_STORE_ERROR = "Settings store unavailable"


def _safety_limits() -> SafetyLimits:
    """Build the read-only safety block from the enforcing code and config."""
    return SafetyLimits(
        max_position_size_pct=MAX_POSITION_SIZE_PCT,
        max_risk_score=MAX_RISK_SCORE,
        min_consensus_confidence_pct=REQUIRED_CONFIDENCE,
        live_max_drawdown_pct=settings.live_max_drawdown_pct,
        minimum_paper_trades=settings.minimum_paper_trades,
        minimum_paper_days=settings.minimum_paper_days,
        live_trading_enabled=settings.live_trading_enabled,
    )


@router.get("", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)) -> SettingsResponse:
    """Return effective safety limits and the persisted dashboard preferences."""
    try:
        preferences = await settings_service.load_preferences(db)
    except Exception as exc:  # noqa: BLE001 - surface a stable 503 to the dashboard
        logger.error("Could not load dashboard preferences", exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_STORE_ERROR) from exc

    return SettingsResponse(safety=_safety_limits(), preferences=preferences)


@router.put("/preferences", response_model=SettingsResponse)
async def update_preferences(
    preferences: DashboardPreferences,
    db: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    """Persist dashboard preferences and return the effective settings."""
    try:
        saved = await settings_service.save_preferences(db, preferences)
    except Exception as exc:  # noqa: BLE001 - surface a stable 503 to the dashboard
        logger.error("Could not save dashboard preferences", exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_STORE_ERROR) from exc

    return SettingsResponse(safety=_safety_limits(), preferences=saved)
