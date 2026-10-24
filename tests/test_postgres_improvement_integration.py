"""Real-PostgreSQL integration tests for improvement-history persistence.

These tests are opt-in. They run only when ``ARES_TEST_POSTGRES_URL`` points at
a disposable PostgreSQL database whose name contains ``test``; CI sets it in
the dedicated ``postgres-integration`` job. The unit tests mock the SQLAlchemy
session, so this module covers the parts only PostgreSQL can prove:

* the service commits a reflection run and its JSONB fields;
* a separate connection sees the committed rows;
* generated records are linked to the run that produced them;
* the route list/metrics/apply round-trip reads and writes the same tables;
* malformed and unknown record IDs return **404** without touching another row.

The fixture deletes only ``improvement_records`` and ``reflection_runs``. The
database name guard below is a safety gate: never point this at a real ledger.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from agents.improvement import StrategyImprovementEngine
from backend.core.dependencies import get_db
from backend.routers import agents as agents_router
from backend.services import improvement_service

_TEST_DATABASE_URL = os.getenv("ARES_TEST_POSTGRES_URL")
if not _TEST_DATABASE_URL:
    if os.getenv("ARES_REQUIRE_POSTGRES_INTEGRATION"):
        raise RuntimeError(
            "ARES_REQUIRE_POSTGRES_INTEGRATION is set but ARES_TEST_POSTGRES_URL is "
            "missing; the PostgreSQL integration job must not skip silently"
        )
    pytest.skip(
        "Set ARES_TEST_POSTGRES_URL to a disposable PostgreSQL database to run these tests",
        allow_module_level=True,
    )

assert _TEST_DATABASE_URL is not None  # narrowed for type checkers after pytest.skip
DATABASE_URL: str = _TEST_DATABASE_URL
_DATABASE_NAME = make_url(DATABASE_URL).database or ""
if "test" not in _DATABASE_NAME.lower():
    raise RuntimeError(
        f"ARES_TEST_POSTGRES_URL database {_DATABASE_NAME!r} is not a test database; "
        "refusing to delete its improvement history"
    )


def _new_engine() -> AsyncEngine:
    """Create a fresh engine so each call behaves like a separate process."""
    return create_async_engine(DATABASE_URL, poolclass=NullPool)


async def _delete_history(engine: AsyncEngine) -> None:
    """Remove only the two tables this module owns, child rows first."""
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM improvement_records"))
        await connection.execute(text("DELETE FROM reflection_runs"))


async def _rows(sql: str, params: dict[str, Any] | None = None) -> list[tuple[Any, ...]]:
    """Read committed state through a separate engine, as an observer process would."""
    engine = _new_engine()
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql), params or {})
            return [tuple(row) for row in result.all()]
    finally:
        await engine.dispose()


async def _execute(sql: str, params: dict[str, Any] | None = None) -> None:
    """Write state directly, bypassing the service for setup."""
    engine = _new_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(text(sql), params or {})
    finally:
        await engine.dispose()


async def _seed_reflections(entries: list[tuple[bool, float, list[str]]]) -> None:
    """Insert reflection rows with a strict chronological order."""
    engine = _new_engine()
    base = datetime.now(UTC) - timedelta(minutes=len(entries) + 1)
    try:
        async with engine.begin() as connection:
            for index, (executed, accuracy, suggestions) in enumerate(entries):
                await connection.execute(
                    text(
                        """
                        INSERT INTO reflection_runs (
                            evaluation, confidence_accuracy, improvement_suggestions,
                            knowledge_updates, created_at
                        )
                        VALUES (
                            :evaluation, :accuracy, CAST(:suggestions AS JSONB),
                            CAST('[]' AS JSONB), :created_at
                        )
                        """
                    ),
                    {
                        "evaluation": (
                            "Trade executed: long at $100" if executed else "Trade not executed: no consensus"
                        ),
                        "accuracy": accuracy,
                        "suggestions": json.dumps(suggestions),
                        "created_at": base + timedelta(seconds=index),
                    },
                )
    finally:
        await engine.dispose()


def _json_array(value: Any) -> list[Any]:
    if isinstance(value, str):
        decoded = json.loads(value)
        assert isinstance(decoded, list)
        return decoded
    assert isinstance(value, list)
    return value


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        decoded = json.loads(value)
        assert isinstance(decoded, dict)
        return decoded
    assert isinstance(value, dict)
    return value


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Provide a session factory over a clean pair of tables."""
    engine = _new_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _delete_history(engine)
    try:
        yield factory
    finally:
        await _delete_history(engine)
        await engine.dispose()


@pytest.fixture
async def client(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    """Run the real router against the real session factory."""

    async def _test_db() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = FastAPI()
    app.include_router(agents_router.router)
    app.dependency_overrides[get_db] = _test_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as http:
        yield http


async def test_record_and_analyze_persists_a_run_and_generated_records(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    seed: list[tuple[bool, float, list[str]]] = [(True, 85.0, list[str]())] * 5 + [
        (True, 85.0, []),
        (True, 85.0, []),
        (False, 85.0, []),
        (False, 85.0, []),
    ]
    await _seed_reflections(seed)

    summary = await improvement_service.record_and_analyze(
        {
            "evaluation": "Trade not executed: no consensus",
            "confidence_accuracy": 80.0,
            "improvement_suggestions": [],
            "knowledge_updates": ["Review entry timing"],
        },
        symbol="BTC-USD",
        session_factory=sessions,
        engine=StrategyImprovementEngine(),
    )

    assert [record.category for record in summary.records] == ["risk_calibration"]
    assert summary.metrics["total_runs"] == 5

    runs = await _rows("SELECT symbol, confidence_accuracy, knowledge_updates FROM reflection_runs ORDER BY created_at")
    assert len(runs) == 10
    latest = runs[-1]
    assert latest[0] == "BTC-USD"
    assert float(latest[1]) == 80.0
    assert _json_array(latest[2]) == ["Review entry timing"]

    records = await _rows(
        """
        SELECT reflection_run_id, category, severity, metric_before, metric_after,
               rationale, suggested_params
        FROM improvement_records
        """
    )
    assert len(records) == 1
    assert records[0][0] == summary.reflection_run_id
    assert records[0][1] == "risk_calibration"
    assert records[0][2] == "high"
    assert float(records[0][3]) == 100.0
    assert float(records[0][4]) == 0.0
    assert "dropped" in records[0][5]
    assert _json_object(records[0][6]) == {"max_drawdown_pct": 15.0}


async def test_committed_reflection_runs_survive_a_new_connection(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    summary = await improvement_service.record_and_analyze(
        {
            "evaluation": "Trade executed: long at $100",
            "confidence_accuracy": 82.0,
            "improvement_suggestions": ["Review entry timing"],
            "knowledge_updates": [],
        },
        symbol="ETH-USD",
        request_id=str(uuid4()),
        session_id=str(uuid4()),
        errors=[{"agent": "news", "error": "timeout"}],
        session_factory=sessions,
        engine=StrategyImprovementEngine(),
    )

    rows = await _rows(
        """
        SELECT symbol, confidence_accuracy, improvement_suggestions, errors
        FROM reflection_runs
        WHERE id = :run_id
        """,
        {"run_id": summary.reflection_run_id},
    )
    assert len(rows) == 1
    assert rows[0][0] == "ETH-USD"
    assert float(rows[0][1]) == 82.0
    assert _json_array(rows[0][2]) == ["Review entry timing"]
    assert _json_array(rows[0][3]) == [{"agent": "news", "error": "timeout"}]


async def test_route_list_metrics_and_apply_round_trip(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_reflections([(True, 80.0, [])] * 5)
    record_id = uuid4()
    await _execute(
        """
        INSERT INTO improvement_records (
            id, category, description, severity, metric_before, metric_after,
            rationale, suggested_params
        )
        VALUES (
            :record_id, 'risk_calibration', 'Execution rate declined', 'high',
            80.0, 60.0, 'Review risk thresholds', CAST(:params AS JSONB)
        )
        """,
        {"record_id": record_id, "params": json.dumps({"max_drawdown_pct": 15.0})},
    )

    listed = await client.get("/api/v1/agents/improvements")
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [str(record_id)]
    assert listed.json()[0]["suggested_params"] == {"max_drawdown_pct": 15.0}
    assert listed.json()[0]["applied"] is False

    metrics = await client.get("/api/v1/agents/improvements/metrics")
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["total_runs"] == 5.0
    assert metrics.json()["execution_rate"] == 100.0
    assert metrics.json()["avg_confidence_accuracy"] == 80.0

    applied = await client.post(
        "/api/v1/agents/improvements/apply",
        json={"record_id": str(record_id)},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json() == {"success": True, "record_id": str(record_id)}

    rows = await _rows(
        "SELECT applied, applied_at FROM improvement_records WHERE id = :record_id",
        {"record_id": record_id},
    )
    assert rows[0][0] is True
    assert rows[0][1] is not None

    # Applying twice is idempotent and keeps the original applied_at.
    again = await client.post(
        "/api/v1/agents/improvements/apply",
        json={"record_id": str(record_id)},
    )
    assert again.status_code == 200
    rows = await _rows(
        "SELECT applied_at FROM improvement_records WHERE id = :record_id",
        {"record_id": record_id},
    )
    assert rows[0][0] is not None


async def test_unknown_and_malformed_record_ids_return_404(client: AsyncClient) -> None:
    unknown = await client.post(
        "/api/v1/agents/improvements/apply",
        json={"record_id": str(uuid4())},
    )
    assert unknown.status_code == 404

    malformed = await client.post(
        "/api/v1/agents/improvements/apply",
        json={"record_id": "not-a-uuid"},
    )
    assert malformed.status_code == 404


async def test_empty_history_returns_zero_metrics(client: AsyncClient) -> None:
    response = await client.get("/api/v1/agents/improvements/metrics")

    assert response.status_code == 200
    assert response.json() == {
        "avg_confidence_accuracy": 0.0,
        "execution_rate": 0.0,
        "error_rate": 0.0,
        "total_runs": 0.0,
    }


async def test_list_returns_newest_records_first(
    client: AsyncClient,
) -> None:
    older = uuid4()
    newer = uuid4()
    await _execute(
        """
        INSERT INTO improvement_records (id, category, description, severity, created_at)
        VALUES
            (:older, 'agent_config', 'Older record', 'medium', NOW() - INTERVAL '1 hour'),
            (:newer, 'agent_config', 'Newer record', 'medium', NOW())
        """,
        {"older": older, "newer": newer},
    )

    response = await client.get("/api/v1/agents/improvements")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(newer), str(older)]
