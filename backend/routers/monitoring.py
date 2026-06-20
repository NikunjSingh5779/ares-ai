"""Monitoring & risk API router.

Endpoints:
    GET /api/v1/metrics — System-wide metrics
    GET /api/v1/risk    — Current risk assessment
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.routers.analysis import get_last_state

router = APIRouter(prefix="/api/v1", tags=["monitoring"])


@router.get("/metrics")
async def metrics() -> dict[str, Any]:
    """Get system-level metrics.

    Returns agent run counts, error counts, and system health.
    """
    state = get_last_state()
    status = state.pipeline_status if state else None

    return {
        "total_runs": 1 if status else 0,
        "total_agents_executed": len(status.completed_nodes) if status else 0,
        "total_errors": len(state.errors) if state and state.errors else 0,
        "total_failures": len(status.failed_nodes) if status else 0,
        "degraded": state.degraded if state else False,
        "total_latency_ms": state.total_latency_ms if state else 0,
    }


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
