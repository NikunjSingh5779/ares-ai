"""Tests for the enriched health endpoint."""

from __future__ import annotations

import io
import logging
from unittest.mock import AsyncMock, patch

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
    from starlette.testclient import TestClient

    from backend.main import app

    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "ARES AI"
        assert "docs" in data
        assert "health" in data


def _fake_all_ok() -> bool:
    """Synchronous stand-in — not an async function, so it will fail under await."""
    return True


@pytest.mark.asyncio
async def test_health_database_unreachable(monkeypatch) -> None:
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
async def test_health_redis_unreachable(monkeypatch) -> None:
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
async def test_health_chromadb_unreachable(monkeypatch) -> None:
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
async def test_health_all_down(monkeypatch) -> None:
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


@pytest.mark.asyncio
async def test_check_redis_exception_logs() -> None:
    """When Redis is unreachable, _check_redis logs at DEBUG and returns False.

    Uses a dedicated test handler on the ``ares`` logger rather than caplog
    or capsys because importing ``backend.main`` triggers
    ``setup_logging()`` at module level, which clears root logger handlers
    (including caplog's ``_CapLogHandler``) and caches ``sys.stdout`` at
    import time, making capsys unreliable across tests.
    """
    from backend.main import _check_redis

    mock_client = AsyncMock(spec=["ping", "aclose"])
    mock_client.ping.side_effect = ConnectionError("Redis connection refused")

    test_handler = logging.StreamHandler(io.StringIO())
    test_handler.setLevel(logging.DEBUG)
    ares_logger = logging.getLogger("ares")
    ares_logger.setLevel(logging.DEBUG)
    ares_logger.addHandler(test_handler)
    try:
        with patch("redis.asyncio.Redis", return_value=mock_client):
            result = await _check_redis()
    finally:
        ares_logger.removeHandler(test_handler)

    assert result is False
    output = test_handler.stream.getvalue()
    assert "Redis health check failed" in output


@pytest.mark.asyncio
async def test_check_chromadb_exception_logs() -> None:
    """When ChromaDB is unreachable, _check_chromadb logs at DEBUG and returns False."""
    from backend.main import _check_chromadb

    test_handler = logging.StreamHandler(io.StringIO())
    test_handler.setLevel(logging.DEBUG)
    ares_logger = logging.getLogger("ares")
    ares_logger.setLevel(logging.DEBUG)
    ares_logger.addHandler(test_handler)
    try:
        with patch("chromadb.HttpClient", side_effect=ConnectionError("ChromaDB connection refused")):
            result = await _check_chromadb()
    finally:
        ares_logger.removeHandler(test_handler)

    assert result is False
    output = test_handler.stream.getvalue()
    assert "ChromaDB health check failed" in output


@pytest.mark.asyncio
async def test_check_connection_exception_logs(caplog: pytest.LogCaptureFixture) -> None:
    """When the database engine raises, check_connection logs at DEBUG and returns False.

    Uses caplog because ``database.connection`` does **not** call ``setup_logging()``
    at module level — that side effect is unique to ``backend.main``.
    """
    from unittest.mock import patch

    from database.connection import check_connection

    class _FailingEngine:
        """Minimal synchronous mock — raises ``ConnectionError`` when used in
        ``async with engine.connect() as conn:``.

        ``AsyncEngine.connect()`` is a read-only descriptor, and ``AsyncMock``
        wraps side effects in coroutines that trigger ``RuntimeWarning`` when
        they aren't properly awaited.  This class avoids both problems by
        returning a connection whose ``__aenter__`` raises synchronously.
        """

        class _FailingConnection:
            async def __aenter__(self) -> None:
                raise ConnectionError("Database unavailable")

            async def __aexit__(self, *args: object) -> None:
                pass

        def connect(self) -> _FailingConnection:
            return self._FailingConnection()

    with patch("database.connection.engine", _FailingEngine()), caplog.at_level(logging.DEBUG):
        result = await check_connection()

    assert result is False
    assert any("Database connection check failed" in rec.message for rec in caplog.records)
