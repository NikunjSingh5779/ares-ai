"""Real-PostgreSQL integration tests for the draft-strategy routes.

These tests are opt-in. They run only when ``ARES_TEST_POSTGRES_URL`` points at
a disposable PostgreSQL database whose name contains ``test``; CI sets it in
the dedicated ``postgres-integration`` job. The unit tests mock the SQLAlchemy
session, so this module covers the parts only PostgreSQL can prove:

* the route -> service -> JSONB insert round-trip;
* committed rows are visible through a separate connection;
* an edit bumps ``version`` and leaves lifecycle fields server-owned;
* a row promoted outside the API returns **409** and is not overwritten;
* lifecycle/live-enablement fields are **422** before any write;
* missing rows return **404**.

The fixture deletes only the ``strategies`` table. The database name guard
below is a safety gate: never point this at a real ledger.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.core.dependencies import get_db
from backend.routers import strategies as strategies_router

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
        f"ARES_TEST_POSTGRES_URL database {_DATABASE_NAME!r} is not a test database; refusing to delete its strategies"
    )


def _new_engine() -> AsyncEngine:
    """Create a fresh engine so each call behaves like a separate process."""
    return create_async_engine(DATABASE_URL, poolclass=NullPool)


async def _delete_strategies(engine: AsyncEngine) -> None:
    """Remove only draft rows; never truncate users or the paper ledger."""
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM strategies"))


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
    """Write state directly, bypassing the API for boundary tests."""
    engine = _new_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(text(sql), params or {})
    finally:
        await engine.dispose()


def _json_object(value: Any) -> dict[str, Any]:
    """Decode a JSONB value returned by asyncpg or a test double."""
    if isinstance(value, str):
        decoded = json.loads(value)
        assert isinstance(decoded, dict)
        return decoded
    assert isinstance(value, dict)
    return value


def _create_payload(**overrides: Any) -> dict[str, Any]:
    """A valid draft payload with room for rejected lifecycle fields."""
    payload: dict[str, Any] = {
        "name": "  Momentum Draft  ",
        "description": "  Trend following draft  ",
        "strategy_type": "momentum",
        "config": {"indicators": ["SMA", "rsi", "sma"]},
        "parameters": {
            "position_size_pct": 10,
            "stop_loss_pct": 5,
            "take_profit_pct": 15,
        },
    }
    payload.update(overrides)
    return payload


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Run the real router against a real session, with a clean strategy table."""
    engine = _new_engine()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def _test_db() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = FastAPI()
    app.include_router(strategies_router.router)
    app.dependency_overrides[get_db] = _test_db

    await _delete_strategies(engine)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as http:
            yield http
    finally:
        await _delete_strategies(engine)
        await engine.dispose()


async def test_create_get_and_list_persist_committed_jsonb(client: AsyncClient) -> None:
    response = await client.post("/api/v1/strategies", json=_create_payload())

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["name"] == "Momentum Draft"
    assert created["description"] == "Trend following draft"
    assert created["strategy_type"] == "momentum"
    assert created["config"] == {"indicators": ["sma", "rsi"]}
    assert created["parameters"] == {
        "position_size_pct": 10.0,
        "stop_loss_pct": 5.0,
        "take_profit_pct": 15.0,
    }
    assert created["version"] == 1
    assert created["status"] == "draft"
    assert created["paper_trade_closed_trades"] == 0
    assert created["live_trading_enabled"] is False

    strategy_id = UUID(created["id"])
    rows = await _rows(
        """
        SELECT name, description, strategy_type, config, parameters, version, status,
               paper_trade_closed_trades, live_trading_enabled
        FROM strategies
        WHERE id = :strategy_id
        """,
        {"strategy_id": strategy_id},
    )
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == "Momentum Draft"
    assert row[1] == "Trend following draft"
    assert row[2] == "momentum"
    assert _json_object(row[3]) == {"indicators": ["sma", "rsi"]}
    assert _json_object(row[4]) == {
        "position_size_pct": 10.0,
        "stop_loss_pct": 5.0,
        "take_profit_pct": 15.0,
    }
    assert row[5] == 1
    assert row[6] == "draft"
    assert row[7] == 0
    assert row[8] is False

    fetched = await client.get(f"/api/v1/strategies/{strategy_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]
    assert fetched.json()["name"] == created["name"]

    listed = await client.get("/api/v1/strategies")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [created["id"]]


async def test_update_bumps_version_and_promoted_row_is_not_editable(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/strategies", json=_create_payload(name="Momentum Draft"))).json()
    strategy_id = UUID(created["id"])

    response = await client.put(
        f"/api/v1/strategies/{strategy_id}",
        json={
            "name": "Momentum v2",
            "config": {"indicators": ["ema", "macd"]},
            "parameters": {
                "position_size_pct": 5,
                "stop_loss_pct": 2,
                "take_profit_pct": 8,
            },
        },
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["name"] == "Momentum v2"
    assert updated["version"] == 2
    assert updated["config"] == {"indicators": ["ema", "macd"]}
    assert updated["status"] == "draft"
    assert updated["live_trading_enabled"] is False
    assert updated["paper_trade_closed_trades"] == 0

    rows = await _rows(
        """
        SELECT name, config, parameters, version, status, live_trading_enabled,
               paper_trade_closed_trades
        FROM strategies
        WHERE id = :strategy_id
        """,
        {"strategy_id": strategy_id},
    )
    assert len(rows) == 1
    assert rows[0][0] == "Momentum v2"
    assert _json_object(rows[0][1]) == {"indicators": ["ema", "macd"]}
    assert _json_object(rows[0][2]) == {
        "position_size_pct": 5.0,
        "stop_loss_pct": 2.0,
        "take_profit_pct": 8.0,
    }
    assert rows[0][3] == 2
    assert rows[0][4] == "draft"
    assert rows[0][5] is False
    assert rows[0][6] == 0

    # A promotion outside this API must make the next edit fail closed.
    await _execute(
        """
        UPDATE strategies
        SET name = 'Promoted directly', status = 'backtesting'
        WHERE id = :strategy_id
        """,
        {"strategy_id": strategy_id},
    )
    denied = await client.put(
        f"/api/v1/strategies/{strategy_id}",
        json={"name": "Should not write"},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"] == "Only draft or paused strategies can be edited"

    rows = await _rows(
        "SELECT name, version, status FROM strategies WHERE id = :strategy_id",
        {"strategy_id": strategy_id},
    )
    assert rows == [("Promoted directly", 2, "backtesting")]


async def test_paused_strategy_remains_editable(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/strategies", json=_create_payload(name="Paused Draft"))).json()
    strategy_id = UUID(created["id"])
    await _execute(
        "UPDATE strategies SET status = 'paused' WHERE id = :strategy_id",
        {"strategy_id": strategy_id},
    )

    response = await client.put(
        f"/api/v1/strategies/{strategy_id}",
        json={"name": "Paused Draft v2"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Paused Draft v2"
    assert response.json()["version"] == 2
    assert response.json()["status"] == "paused"

    rows = await _rows(
        "SELECT name, version, status FROM strategies WHERE id = :strategy_id",
        {"strategy_id": strategy_id},
    )
    assert rows == [("Paused Draft v2", 2, "paused")]


@pytest.mark.parametrize(
    "extra",
    [
        {"status": "live_trading"},
        {"live_trading_enabled": True},
        {"min_paper_trades_required": 0},
        {"paper_trade_closed_trades": 50},
    ],
)
async def test_create_rejects_lifecycle_or_live_fields(
    client: AsyncClient,
    extra: dict[str, Any],
) -> None:
    response = await client.post("/api/v1/strategies", json=_create_payload(**extra))

    assert response.status_code == 422
    rows = await _rows("SELECT count(*) FROM strategies")
    assert int(rows[0][0]) == 0


@pytest.mark.parametrize(
    "extra",
    [
        {"status": "live_trading"},
        {"live_trading_enabled": True},
        {"min_paper_trades_required": 0},
        {"paper_trade_closed_trades": 50},
    ],
)
async def test_update_rejects_lifecycle_or_live_fields(
    client: AsyncClient,
    extra: dict[str, Any],
) -> None:
    created = (await client.post("/api/v1/strategies", json=_create_payload(name="Immutable Draft"))).json()
    strategy_id = UUID(created["id"])

    response = await client.put(
        f"/api/v1/strategies/{strategy_id}",
        json={"name": "Should not write", **extra},
    )

    assert response.status_code == 422
    rows = await _rows(
        "SELECT name, version, status, live_trading_enabled FROM strategies WHERE id = :strategy_id",
        {"strategy_id": strategy_id},
    )
    assert rows == [("Immutable Draft", 1, "draft", False)]


async def test_missing_strategy_returns_404(client: AsyncClient) -> None:
    missing = uuid4()

    fetched = await client.get(f"/api/v1/strategies/{missing}")
    assert fetched.status_code == 404
    assert fetched.json()["detail"] == "Strategy not found"

    updated = await client.put(f"/api/v1/strategies/{missing}", json={"name": "Gone"})
    assert updated.status_code == 404
    assert updated.json()["detail"] == "Strategy not found"

    rows = await _rows("SELECT count(*) FROM strategies")
    assert int(rows[0][0]) == 0
