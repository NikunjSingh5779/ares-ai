"""Journal & Memory API router.

Endpoints:
    GET /api/v1/journal — Return the journal output from the last pipeline run
    GET /api/v1/memory  — Return memory records from the last run
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from backend.core.dependencies import async_session_factory
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


@router.get("/journal/history")
async def journal_history(limit: int = 50) -> list[dict[str, Any]]:
    """Get historical journal entries."""
    query = text("""
        SELECT id, entry_type, title, content, sentiment, mistakes_detected, lessons_learned, created_at
        FROM journal
        ORDER BY created_at DESC
        LIMIT :limit
    """)
    async with async_session_factory() as session:
        result = await session.execute(query, {"limit": limit})
        rows = result.fetchall()

    entries = []
    for row in rows:
        entries.append({
            "id": str(row.id),
            "entry_type": row.entry_type,
            "title": row.title,
            "content": row.content,
            "sentiment": row.sentiment,
            "mistakes_detected": row.mistakes_detected,
            "lessons_learned": row.lessons_learned,
            "created_at": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else str(row.created_at),
        })

    return entries
