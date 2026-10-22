"""Monitoring & risk API router.

Endpoints:
    GET /api/v1/metrics — System-wide metrics
    GET /api/v1/risk    — Current risk assessment
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.core.metrics import get_metrics_snapshot
from backend.routers.analysis import get_last_state

router = APIRouter(prefix="/api/v1", tags=["monitoring"])


@router.get("/metrics")
async def metrics() -> dict[str, Any]:
    """Get system-wide metrics from the Prometheus registry.

    Values are process-local counters since the API process started. They do
    not depend on the last analysis run; use ``/agents/status`` or ``/risk``
    for per-run state.
    """
    return get_metrics_snapshot()


@router.get("/risk")
async def risk() -> dict[str, Any]:
    """Get current risk state from the last pipeline run."""
    state = get_last_state()
    if state is None or state.risk is None:
        return {
            "approved": False,
            "risk_score": 0,
            "max_position_size": None,
            "stop_loss": None,
            "reasons": [],
            "rationale": "No risk assessment available",
        }

    return state.risk.model_dump()
