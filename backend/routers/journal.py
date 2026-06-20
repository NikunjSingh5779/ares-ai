"""Journal & Memory API router.

Endpoints:
    GET /api/v1/journal — Return the journal output from the last pipeline run
    GET /api/v1/memory  — Return memory records from the last run
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.routers.analysis import get_last_state

router = APIRouter(prefix="/api/v1", tags=["journal"])


@router.get("/journal")
async def journal() -> dict[str, Any]:
    """Get the journal output from the last pipeline run."""
    state = get_last_state()
    if state is None or state.journal is None:
        return {
            "entry_id": None,
            "mistakes": [],
            "lessons": [],
            "rationale": "No pipeline run yet",
        }

    return state.journal.model_dump()


@router.get("/memory")
async def memory() -> dict[str, Any]:
    """Get memory records from the last pipeline run."""
    state = get_last_state()
    if state is None or state.memory is None:
        return {
            "relevant_memories": [],
            "consolidated": False,
            "rationale": "No pipeline run yet",
        }

    return state.memory.model_dump()
