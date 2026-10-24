"""Tests for the improvement-history API.

The routes now read PostgreSQL through the persistence service. These tests
mock the service boundary so they stay fast and prove the HTTP contract:
list, apply, metrics, validation, 404, and 503.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.dependencies import get_db
from backend.routers import agents as agents_router
from backend.services import improvement_service

NOW = datetime.now(UTC)


def _record(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": str(uuid4()),
        "timestamp": NOW.isoformat(),
        "category": "risk_calibration",
        "description": "Execution rate declined by 20.0% over recent runs",
        "severity": "high",
        "metric_before": 80.0,
        "metric_after": 60.0,
        "applied": False,
        "rationale": "Review risk thresholds",
        "suggested_params": {"max_drawdown_pct": 15.0},
    }
    values.update(overrides)
    return values


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(agents_router.router)
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app)


@pytest.fixture
def fake_list(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=[_record()])
    monkeypatch.setattr(improvement_service, "list_records", mock)
    return mock


@pytest.fixture
def fake_apply(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=True)
    monkeypatch.setattr(improvement_service, "apply_record", mock)
    return mock


@pytest.fixture
def fake_metrics(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(
        return_value={
            "avg_confidence_accuracy": 82.0,
            "execution_rate": 60.0,
            "error_rate": 0.0,
            "total_runs": 5.0,
        }
    )
    monkeypatch.setattr(improvement_service, "metrics", mock)
    return mock


def test_list_improvements_returns_records_and_limit(client: TestClient, fake_list: AsyncMock) -> None:
    response = client.get("/api/v1/agents/improvements?limit=5")

    assert response.status_code == 200
    assert response.json()[0]["category"] == "risk_calibration"
    assert response.json()[0]["suggested_params"] == {"max_drawdown_pct": 15.0}
    assert fake_list.await_args is not None
    assert fake_list.await_args.args[1] == 5


def test_list_improvements_rejects_an_out_of_range_limit(client: TestClient) -> None:
    assert client.get("/api/v1/agents/improvements?limit=0").status_code == 422
    assert client.get("/api/v1/agents/improvements?limit=101").status_code == 422


def test_apply_requires_a_record_id(client: TestClient) -> None:
    response = client.post("/api/v1/agents/improvements/apply", json={})

    assert response.status_code == 400
    assert response.json()["detail"] == "record_id is required"


def test_apply_unknown_record_returns_404(client: TestClient, fake_apply: AsyncMock) -> None:
    fake_apply.return_value = False
    record_id = str(uuid4())

    response = client.post("/api/v1/agents/improvements/apply", json={"record_id": record_id})

    assert response.status_code == 404
    assert record_id in response.json()["detail"]


def test_apply_success_marks_the_record(client: TestClient, fake_apply: AsyncMock) -> None:
    record_id = str(uuid4())

    response = client.post("/api/v1/agents/improvements/apply", json={"record_id": record_id})

    assert response.status_code == 200
    assert response.json() == {"success": True, "record_id": record_id}
    assert fake_apply.await_args is not None
    assert fake_apply.await_args.args[1] == record_id


def test_metrics_returns_the_aggregate_summary(client: TestClient, fake_metrics: AsyncMock) -> None:
    response = client.get("/api/v1/agents/improvements/metrics")

    assert response.status_code == 200
    assert response.json()["total_runs"] == 5.0
    assert response.json()["execution_rate"] == 60.0


def test_list_returns_503_when_the_store_is_unavailable(client: TestClient, fake_list: AsyncMock) -> None:
    fake_list.side_effect = RuntimeError("database down")

    response = client.get("/api/v1/agents/improvements")

    assert response.status_code == 503
    assert response.json()["detail"] == "Improvement history unavailable"
