"""Tests for the enriched health endpoint."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok_structure() -> None:
    """Verify the health endpoint returns the expected response shape."""
    from backend.main import app

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "service" in data
        assert "checks" in data
        assert data["service"] == "ares-ai"


@pytest.mark.asyncio
async def test_root_endpoint() -> None:
    """Verify the root endpoint returns API info."""
    from backend.main import app
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "ARES AI"
        assert "docs" in data
        assert "health" in data


def _fake_all_ok() -> bool:
    """Synchronous stand-in — not an async function, so it will fail under await."""
    pass


@pytest.mark.asyncio
async def test_health_database_unreachable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Verify health reports degraded when DB is down."""
    monkeypatch.setattr(
        "database.connection.check_connection",
        AsyncMock(return_value=False),
    )
    from backend.main import app

    with TestClient(app) as client:
        response = client.get("/health")
        data = response.json()
        assert data["checks"]["database"] == "unreachable"
        assert data["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_redis_unreachable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Verify health reports degraded when Redis is down."""
    monkeypatch.setattr(
        "backend.main._check_redis",
        AsyncMock(return_value=False),
    )
    from backend.main import app

    with TestClient(app) as client:
        response = client.get("/health")
        data = response.json()
        assert data["checks"]["redis"] == "unreachable"
        assert data["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_chromadb_unreachable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Verify health reports degraded when ChromaDB is down."""
    monkeypatch.setattr(
        "backend.main._check_chromadb",
        AsyncMock(return_value=False),
    )
    from backend.main import app

    with TestClient(app) as client:
        response = client.get("/health")
        data = response.json()
        assert data["checks"]["chromadb"] == "unreachable"
        assert data["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_all_down(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Verify health reports degraded when all services are down."""
    monkeypatch.setattr("database.connection.check_connection", AsyncMock(return_value=False))
    monkeypatch.setattr("backend.main._check_redis", AsyncMock(return_value=False))
    monkeypatch.setattr("backend.main._check_chromadb", AsyncMock(return_value=False))
    from backend.main import app

    with TestClient(app) as client:
        response = client.get("/health")
        data = response.json()
        assert data["checks"]["database"] == "unreachable"
        assert data["checks"]["redis"] == "unreachable"
        assert data["checks"]["chromadb"] == "unreachable"
        assert data["status"] == "degraded"
