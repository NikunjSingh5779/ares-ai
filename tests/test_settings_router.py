"""Tests for the settings API.

The safety block must mirror the enforcing constants, and the mutable payload
must never be able to raise a trading limit.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.consensus import REQUIRED_CONFIDENCE
from agents.risk import MAX_POSITION_SIZE_PCT, MAX_RISK_SCORE
from backend.core.dependencies import get_db
from backend.routers import settings as settings_router
from backend.schemas.settings import DashboardPreferences
from backend.services import settings_service
from configs.settings import settings


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(settings_router.router)
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app)


@pytest.fixture
def fake_load(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=DashboardPreferences())
    monkeypatch.setattr(settings_service, "load_preferences", mock)
    return mock


@pytest.fixture
def fake_save(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(side_effect=lambda _db, preferences: preferences)
    monkeypatch.setattr(settings_service, "save_preferences", mock)
    return mock


def test_get_returns_enforced_safety_limits(client: TestClient, fake_load: AsyncMock) -> None:
    response = client.get("/api/v1/settings")

    assert response.status_code == 200
    safety = response.json()["safety"]
    assert safety == {
        "max_position_size_pct": MAX_POSITION_SIZE_PCT,
        "max_risk_score": MAX_RISK_SCORE,
        "min_consensus_confidence_pct": REQUIRED_CONFIDENCE,
        "live_max_drawdown_pct": settings.live_max_drawdown_pct,
        "minimum_paper_trades": settings.minimum_paper_trades,
        "minimum_paper_days": settings.minimum_paper_days,
        "live_trading_enabled": settings.live_trading_enabled,
    }
    fake_load.assert_awaited_once()


def test_get_returns_persisted_preferences(client: TestClient, fake_load: AsyncMock) -> None:
    fake_load.return_value = DashboardPreferences(
        default_symbol="ETH-USD",
        live_refresh_seconds=15,
    )

    response = client.get("/api/v1/settings")

    assert response.status_code == 200
    assert response.json()["preferences"] == {
        "default_symbol": "ETH-USD",
        "live_refresh_seconds": 15,
    }


def test_put_persists_and_normalizes_preferences(client: TestClient, fake_save: AsyncMock) -> None:
    response = client.put(
        "/api/v1/settings/preferences",
        json={"default_symbol": " eth-usd ", "live_refresh_seconds": 10},
    )

    assert response.status_code == 200
    assert response.json()["preferences"] == {
        "default_symbol": "ETH-USD",
        "live_refresh_seconds": 10,
    }
    assert fake_save.await_args is not None
    saved = fake_save.await_args.args[1]
    assert saved.default_symbol == "ETH-USD"
    assert saved.live_refresh_seconds == 10


def test_put_rejects_a_safety_limit_override(client: TestClient, fake_save: AsyncMock) -> None:
    response = client.put(
        "/api/v1/settings/preferences",
        json={
            "default_symbol": "BTC-USD",
            "live_refresh_seconds": 5,
            "safety": {"max_position_size_pct": 100},
        },
    )

    assert response.status_code == 422
    fake_save.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"default_symbol": "bad symbol", "live_refresh_seconds": 5},
        {"default_symbol": "BTC-USD", "live_refresh_seconds": 4},
        {"default_symbol": "BTC-USD", "live_refresh_seconds": 31},
        {"default_symbol": "", "live_refresh_seconds": 5},
        {"default_symbol": "X" * 21, "live_refresh_seconds": 5},
    ],
)
def test_put_rejects_invalid_preferences(
    client: TestClient,
    fake_save: AsyncMock,
    payload: dict[str, object],
) -> None:
    response = client.put("/api/v1/settings/preferences", json=payload)

    assert response.status_code == 422
    fake_save.assert_not_awaited()


def test_get_returns_503_when_store_is_unavailable(
    client: TestClient,
    fake_load: AsyncMock,
) -> None:
    fake_load.side_effect = RuntimeError("database down")

    response = client.get("/api/v1/settings")

    assert response.status_code == 503
    assert response.json()["detail"] == "Settings store unavailable"


def test_put_returns_503_when_store_is_unavailable(
    client: TestClient,
    fake_save: AsyncMock,
) -> None:
    fake_save.side_effect = RuntimeError("database down")

    response = client.put(
        "/api/v1/settings/preferences",
        json={"default_symbol": "BTC-USD", "live_refresh_seconds": 5},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Settings store unavailable"


def test_response_never_contains_secret_material(client: TestClient, fake_load: AsyncMock) -> None:
    response = client.get("/api/v1/settings")

    body = response.text.lower()
    assert "api_secret" not in body
    assert "api_key" not in body
    assert "token" not in body
