"""Strategy draft API.

Endpoints:
    GET    /api/v1/strategies       — list saved strategies
    GET    /api/v1/strategies/{id}  — read one strategy
    POST   /api/v1/strategies       — create a draft
    PUT    /api/v1/strategies/{id}  — update a draft or paused strategy

The request models forbid status, live-enablement, and promotion fields. Those
remain server-owned so this router cannot be used to promote a strategy or
bypass the paper-trading gate.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.schemas.strategy import StrategyCreate, StrategyResponse, StrategyUpdate
from backend.services import strategy_service

logger = logging.getLogger("ares.api.strategies")

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])

_STORE_ERROR = "Strategy store unavailable"


@router.get("", response_model=list[StrategyResponse])
async def list_strategies(
    limit: Annotated[int, Query(ge=1, le=100, description="Maximum strategies to return")] = 50,
    db: AsyncSession = Depends(get_db),
) -> list[StrategyResponse]:
    """Return saved strategies, newest first."""
    try:
        return await strategy_service.list_strategies(db, limit)
    except Exception as exc:  # noqa: BLE001 - stable 503 for the dashboard
        logger.error("Could not list strategies", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_STORE_ERROR,
        ) from exc


@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(
    strategy_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> StrategyResponse:
    """Return one saved strategy or 404."""
    try:
        strategy = await strategy_service.get_strategy(db, strategy_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not read strategy", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_STORE_ERROR,
        ) from exc
    if strategy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    return strategy


@router.post("", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy(
    payload: StrategyCreate,
    db: AsyncSession = Depends(get_db),
) -> StrategyResponse:
    """Create a draft strategy. Status and live fields are server-owned."""
    try:
        return await strategy_service.create_strategy(db, payload)
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not create strategy", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_STORE_ERROR,
        ) from exc


@router.put("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: UUID,
    payload: StrategyUpdate,
    db: AsyncSession = Depends(get_db),
) -> StrategyResponse:
    """Update a draft or paused strategy without touching lifecycle fields."""
    try:
        return await strategy_service.update_strategy(db, strategy_id, payload)
    except strategy_service.StrategyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found") from exc
    except strategy_service.StrategyNotEditableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft or paused strategies can be edited",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not update strategy", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_STORE_ERROR,
        ) from exc
