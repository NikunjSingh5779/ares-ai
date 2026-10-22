"""Tests for the draft-strategy API.

The router must never accept lifecycle or live-enablement fields. Promotion is a
separate, gated path; a draft API must not be able to bypass it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.dependencies import get_db
from backend.routers import strategies as strategies_router
from backend.schemas.strategy import (
    StrategyConfig,
    StrategyCreate,
    StrategyParameters,
    StrategyResponse,
    StrategyUpdate,
)
from backend.services import strategy_service

NOW = datetime.now(UTC)
STRATEGY_ID = uuid4()


def _response(**overrides: object) -> StrategyResponse:
    values: dict[str, object] = {
        "id": STRATEGY_ID,
        "name": "Momentum Draft",
        "description": "Trend following draft",
        "strategy_type": "momentum",
        "config": StrategyConfig(indicators=["sma", "rsi"]),
        "parameters": StrategyParameters(position_size_pct=10),
        "version": 1,
        "status": "draft",
        "paper_trade_closed_trades": 0,
        "live_trading_enabled": False,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return StrategyResponse.model_validate(values)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(strategies_router.router)
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app)


@pytest.fixture
def fake_list(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=[_response()])
    monkeypatch.setattr(strategy_service, "list_strategies", mock)
    return mock


@pytest.fixture
def fake_get(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=_response())
    monkeypatch.setattr(strategy_service, "get_strategy", mock)
    return mock


@pytest.fixture
def fake_create(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(side_effect=lambda _db, payload: _response(name=payload.name))
    monkeypatch.setattr(strategy_service, "create_strategy", mock)
    return mock


@pytest.fixture
def fake_update(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(side_effect=lambda _db, _id, payload: _response(name=payload.name or "Momentum Draft"))
    monkeypatch.setattr(strategy_service, "update_strategy", mock)
    return mock


def test_list_returns_saved_strategies(client: TestClient, fake_list: AsyncMock) -> None:
    response = client.get("/api/v1/strategies", params={"limit": 10})

    assert response.status_code == 200
    body = response.json()
    assert body[0]["name"] == "Momentum Draft"
    assert body[0]["status"] == "draft"
    assert body[0]["live_trading_enabled"] is False
    assert fake_list.await_args is not None
    assert fake_list.await_args.args[1] == 10


def test_list_rejects_an_out_of_range_limit(client: TestClient, fake_list: AsyncMock) -> None:
    response = client.get("/api/v1/strategies", params={"limit": 101})

    assert response.status_code == 422
    fake_list.assert_not_awaited()


def test_get_returns_one_strategy(client: TestClient, fake_get: AsyncMock) -> None:
    response = client.get(f"/api/v1/strategies/{STRATEGY_ID}")

    assert response.status_code == 200
    assert response.json()["id"] == str(STRATEGY_ID)


def test_get_returns_404_when_missing(client: TestClient, fake_get: AsyncMock) -> None:
    fake_get.return_value = None

    response = client.get(f"/api/v1/strategies/{STRATEGY_ID}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Strategy not found"


def test_create_returns_201_and_strips_the_name(client: TestClient, fake_create: AsyncMock) -> None:
    response = client.post(
        "/api/v1/strategies",
        json={
            "name": "  Momentum Draft  ",
            "description": "  Trend following draft  ",
            "strategy_type": "momentum",
            "config": {"indicators": ["SMA", "rsi", "sma"]},
            "parameters": {"position_size_pct": 10, "stop_loss_pct": 5, "take_profit_pct": 15},
        },
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Momentum Draft"
    assert fake_create.await_args is not None
    created: StrategyCreate = fake_create.await_args.args[1]
    assert created.name == "Momentum Draft"
    assert created.config.indicators == ["sma", "rsi"]


@pytest.mark.parametrize(
    "extra",
    [
        {"status": "live_trading"},
        {"live_trading_enabled": True},
        {"min_paper_trades_required": 0},
        {"paper_trade_closed_trades": 50},
    ],
)
def test_create_rejects_lifecycle_or_live_fields(
    client: TestClient,
    fake_create: AsyncMock,
    extra: dict[str, object],
) -> None:
    payload = {
        "name": "Momentum Draft",
        "strategy_type": "momentum",
        "config": {"indicators": ["sma"]},
        "parameters": {"position_size_pct": 10},
        **extra,
    }

    response = client.post("/api/v1/strategies", json=payload)

    assert response.status_code == 422
    fake_create.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "strategy_type": "momentum"},
        {"name": "X", "strategy_type": "not_a_strategy"},
        {"name": "X", "strategy_type": "momentum", "config": {"indicators": ["bad indicator"]}},
        {"name": "X", "strategy_type": "momentum", "parameters": {"position_size_pct": 0}},
        {"name": "X", "strategy_type": "momentum", "parameters": {"stop_loss_pct": 101}},
    ],
)
def test_create_rejects_invalid_payloads(
    client: TestClient,
    fake_create: AsyncMock,
    payload: dict[str, object],
) -> None:
    response = client.post("/api/v1/strategies", json=payload)

    assert response.status_code == 422
    fake_create.assert_not_awaited()


def test_update_returns_the_new_revision(client: TestClient, fake_update: AsyncMock) -> None:
    response = client.put(
        f"/api/v1/strategies/{STRATEGY_ID}",
        json={"name": "Momentum v2"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Momentum v2"
    assert fake_update.await_args is not None
    update: StrategyUpdate = fake_update.await_args.args[2]
    assert update.name == "Momentum v2"


def test_update_returns_404_when_missing(client: TestClient, fake_update: AsyncMock) -> None:
    fake_update.side_effect = strategy_service.StrategyNotFoundError

    response = client.put(f"/api/v1/strategies/{STRATEGY_ID}", json={"name": "Gone"})

    assert response.status_code == 404


def test_update_returns_409_when_not_editable(client: TestClient, fake_update: AsyncMock) -> None:
    fake_update.side_effect = strategy_service.StrategyNotEditableError

    response = client.put(f"/api/v1/strategies/{STRATEGY_ID}", json={"name": "Nope"})

    assert response.status_code == 409
    assert response.json()["detail"] == "Only draft or paused strategies can be edited"


def test_store_failure_returns_503(client: TestClient, fake_list: AsyncMock) -> None:
    fake_list.side_effect = RuntimeError("database down")

    response = client.get("/api/v1/strategies")

    assert response.status_code == 503
    assert response.json()["detail"] == "Strategy store unavailable"
