"""Durable reflection and improvement history.

The improvement engine is pure analysis; this module owns the PostgreSQL
round-trip. Reflection output is stored as a structured row, then the engine
analyzes it against the committed history so trends survive a restart or a
second worker. Generated suggestions are advisory and never mutate a safety
threshold.

The pipeline hook is best-effort. A history outage must not change a trade
decision, fail a completed run, or bypass a safety gate.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.improvement import (
    ImprovementRecord,
    StrategyImprovementEngine,
    get_improvement_engine,
)
from agents.state import AgentState
from database.connection import async_session_factory

logger = logging.getLogger("ares.improvement")

HISTORY_LIMIT: int = 100
"""Maximum number of reflection runs loaded for trend analysis."""

PERSIST_TIMEOUT_SECONDS: float = 5.0
"""Upper bound on the best-effort pipeline write."""

_RECORD_COLUMNS = """
    id, reflection_run_id, category, description, severity, metric_before,
    metric_after, rationale, suggested_params, applied, applied_at, created_at
"""

_SELECT_HISTORY = text(
    """
    SELECT evaluation, confidence_accuracy, improvement_suggestions
    FROM reflection_runs
    ORDER BY created_at DESC, id DESC
    LIMIT :limit
    """
)

_SELECT_HISTORY_EXCLUDING = text(
    """
    SELECT evaluation, confidence_accuracy, improvement_suggestions
    FROM reflection_runs
    WHERE id <> :run_id
    ORDER BY created_at DESC, id DESC
    LIMIT :limit
    """
)

_INSERT_REFLECTION_RUN = text(
    """
    INSERT INTO reflection_runs (
        session_id, request_id, symbol, evaluation, confidence_accuracy,
        improvement_suggestions, knowledge_updates, errors
    )
    VALUES (
        :session_id, :request_id, :symbol, :evaluation, :confidence_accuracy,
        CAST(:improvement_suggestions AS JSONB), CAST(:knowledge_updates AS JSONB),
        CAST(:errors AS JSONB)
    )
    RETURNING id
    """
)

_INSERT_RECORD = text(
    """
    INSERT INTO improvement_records (
        id, reflection_run_id, category, description, severity, metric_before,
        metric_after, rationale, suggested_params, created_at
    )
    VALUES (
        :id, :reflection_run_id, :category, :description, :severity,
        :metric_before, :metric_after, :rationale,
        CAST(:suggested_params AS JSONB), :created_at
    )
    ON CONFLICT (reflection_run_id, category, description) DO NOTHING
    RETURNING id
    """
)

_SELECT_RECORDS = text(
    f"""
    SELECT {_RECORD_COLUMNS}
    FROM improvement_records
    ORDER BY created_at DESC, id DESC
    LIMIT :limit
    """
)

_APPLY_RECORD = text(
    """
    UPDATE improvement_records
    SET applied = true,
        applied_at = COALESCE(applied_at, NOW())
    WHERE id = :record_id
    RETURNING id
    """
)


@dataclass(frozen=True)
class ImprovementRunSummary:
    """Result of persisting one reflection run and its suggestions."""

    reflection_run_id: UUID
    records: list[ImprovementRecord]
    metrics: dict[str, float]
    warnings: list[str]


def _decode_json(value: Any) -> dict[str, Any]:
    """Decode a JSONB object from PostgreSQL or a test double."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            logger.warning("Stored improvement JSON is invalid; using an empty object")
            return {}
    return value if isinstance(value, dict) else {}


def _decode_list(value: Any) -> list[Any]:
    """Decode a JSONB array from PostgreSQL or a test double."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            logger.warning("Stored reflection JSON is invalid; using an empty list")
            return []
    return value if isinstance(value, list) else []


def _uuid_or_none(value: str | None) -> UUID | None:
    """Parse an optional UUID string; malformed values become NULL."""
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _confidence(value: Any) -> float:
    """Clamp confidence accuracy to the database's 0–100 range."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, number))


def _timestamp(value: str) -> datetime:
    """Parse an engine timestamp, falling back to the current UTC time."""
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def _history_from_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    """Convert newest-first database rows into oldest-first engine history."""
    return [
        {
            "evaluation": row.evaluation,
            "confidence_accuracy": float(row.confidence_accuracy),
            "improvement_suggestions": _decode_list(row.improvement_suggestions),
        }
        for row in reversed(rows)
    ]


def _record_from_row(row: Any) -> dict[str, Any]:
    """Convert an improvement row into the existing API shape."""
    return {
        "id": str(row.id),
        "timestamp": row.created_at.isoformat(),
        "category": row.category,
        "description": row.description,
        "severity": row.severity,
        "metric_before": row.metric_before,
        "metric_after": row.metric_after,
        "applied": row.applied,
        "rationale": row.rationale,
        "suggested_params": _decode_json(row.suggested_params),
    }


async def _insert_reflection_run(
    session: AsyncSession,
    reflection_output: dict[str, Any],
    *,
    symbol: str,
    request_id: str | None,
    session_id: str | None,
    errors: Sequence[dict[str, Any]] | None,
) -> UUID:
    """Insert one reflection run and return its generated UUID."""
    result = await session.execute(
        _INSERT_REFLECTION_RUN,
        {
            "session_id": _uuid_or_none(session_id),
            "request_id": _uuid_or_none(request_id),
            "symbol": (symbol or "")[:30],
            "evaluation": str(reflection_output.get("evaluation", "")),
            "confidence_accuracy": _confidence(reflection_output.get("confidence_accuracy", 0)),
            "improvement_suggestions": json.dumps(list(reflection_output.get("improvement_suggestions", []))),
            "knowledge_updates": json.dumps(list(reflection_output.get("knowledge_updates", []))),
            "errors": json.dumps(list(errors or [])),
        },
    )
    row = result.first()
    if row is None:
        raise RuntimeError("Reflection insert returned no row")
    run_id = row.id
    if not isinstance(run_id, UUID):
        run_id = UUID(str(run_id))
    return run_id


async def _load_history(
    session: AsyncSession,
    *,
    limit: int,
    exclude_run_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """Load committed reflection history, oldest first."""
    capped = max(1, min(limit, HISTORY_LIMIT))
    if exclude_run_id is None:
        result = await session.execute(_SELECT_HISTORY, {"limit": capped})
    else:
        result = await session.execute(
            _SELECT_HISTORY_EXCLUDING,
            {"limit": capped, "run_id": exclude_run_id},
        )
    return _history_from_rows(result.fetchall())


async def _insert_records(
    session: AsyncSession,
    run_id: UUID,
    records: Sequence[ImprovementRecord],
) -> list[ImprovementRecord]:
    """Insert generated records, skipping a duplicate retry of the same run."""
    persisted: list[ImprovementRecord] = []
    for record in records:
        record_uuid = _uuid_or_none(record.id) or uuid4()
        record.id = str(record_uuid)
        result = await session.execute(
            _INSERT_RECORD,
            {
                "id": record_uuid,
                "reflection_run_id": run_id,
                "category": record.category,
                "description": record.description,
                "severity": record.severity,
                "metric_before": record.metric_before,
                "metric_after": record.metric_after,
                "rationale": record.rationale,
                "suggested_params": json.dumps(record.suggested_params),
                "created_at": _timestamp(record.timestamp),
            },
        )
        if result.first() is not None:
            persisted.append(record)
    return persisted


async def record_and_analyze(
    reflection_output: dict[str, Any],
    *,
    symbol: str = "",
    request_id: str | None = None,
    session_id: str | None = None,
    errors: Sequence[dict[str, Any]] | None = None,
    history_limit: int = HISTORY_LIMIT,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    engine: StrategyImprovementEngine | None = None,
) -> ImprovementRunSummary:
    """Persist a reflection run, analyze durable history, and persist records."""
    factory = session_factory or async_session_factory
    analysis_engine = engine or get_improvement_engine()

    async with factory() as session:
        try:
            run_id = await _insert_reflection_run(
                session,
                reflection_output,
                symbol=symbol,
                request_id=request_id,
                session_id=session_id,
                errors=errors,
            )
            history = await _load_history(session, limit=history_limit, exclude_run_id=run_id)
            result = analysis_engine.analyze(reflection_output, history=history)
            persisted = await _insert_records(session, run_id, result.records)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    return ImprovementRunSummary(
        reflection_run_id=run_id,
        records=persisted,
        metrics=result.metrics,
        warnings=result.warnings,
    )


async def list_records(session: AsyncSession, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent improvement records, newest first."""
    result = await session.execute(_SELECT_RECORDS, {"limit": max(1, min(limit, 100))})
    return [_record_from_row(row) for row in result.fetchall()]


async def apply_record(session: AsyncSession, record_id: str) -> bool:
    """Mark one record applied. Returns ``False`` for an unknown or malformed id."""
    try:
        parsed = UUID(record_id)
    except (TypeError, ValueError, AttributeError):
        return False
    result = await session.execute(_APPLY_RECORD, {"record_id": parsed})
    return result.first() is not None


async def metrics(session: AsyncSession, limit: int = HISTORY_LIMIT) -> dict[str, float]:
    """Return aggregate metrics computed from committed reflection history."""
    history = await _load_history(session, limit=limit)
    return get_improvement_engine().metrics_for(history)


async def record_reflection_improvement(state: AgentState) -> None:
    """Best-effort pipeline hook: persist reflection and generated suggestions.

    Any failure is logged and swallowed so a completed trade analysis is never
    changed by an improvement-history outage.
    """
    reflection = state.reflection
    if reflection is None:
        return

    try:
        await asyncio.wait_for(
            record_and_analyze(
                reflection.model_dump(),
                symbol=state.symbol,
                request_id=state.request_id or None,
                session_id=state.session_id or None,
                errors=state.errors,
            ),
            timeout=PERSIST_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001 - best-effort hook must not fail the pipeline
        logger.warning(
            "Improvement history unavailable; pipeline result unchanged",
            exc_info=True,
        )
