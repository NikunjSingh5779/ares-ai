"""Route-level auth enforcement.

The shared ``tests/conftest.py`` fixture overrides ``verify_auth`` for domain
tests. These tests remove that override and prove the real gate is mounted.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.core.dependencies import verify_auth
from backend.main import app
from configs.settings import settings


@pytest.fixture
def unauthenticated_client(monkeypatch) -> Iterator[TestClient]:
    """Client for the real app with the test auth override removed."""
    monkeypatch.setattr(settings, "api_secret_key", "route-auth-test-key")
    saved = app.dependency_overrides.pop(verify_auth, None)
    try:
        yield TestClient(app)
    finally:
        if saved is not None:
            app.dependency_overrides[verify_auth] = saved


def test_protected_get_routes_return_401_without_credentials(unauthenticated_client: TestClient) -> None:
    for path in (
        "/api/v1/portfolio",
        "/api/v1/live/status",
        "/api/v1/agents/status",
    ):
        response = unauthenticated_client.get(path)
        assert response.status_code == 401, f"{path} returned {response.status_code}: {response.text}"


def _iter_api_routes() -> Iterator[tuple[str, APIRoute, list[Any]]]:
    """Yield every mounted APIRoute plus the dependencies inherited at include time.

    FastAPI keeps included routers as ``_IncludedRouter`` wrappers instead of
    flattening them into ``app.routes``, so a plain ``isinstance`` scan would
    miss every domain route.
    """
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route.path, route, []
            continue
        original_router = getattr(route, "original_router", None)
        if original_router is None:
            continue
        context = getattr(route, "include_context", None)
        inherited = list(getattr(context, "dependencies", []) or [])
        for child in original_router.routes:
            if isinstance(child, APIRoute):
                yield child.path, child, inherited


def test_every_api_v1_route_is_mounted_behind_verify_auth() -> None:
    """Guard against a future router being added without the auth dependency."""
    unprotected: list[str] = []
    for path, route, inherited in _iter_api_routes():
        if not path.startswith("/api/v1"):
            continue
        if not any(dep.dependency is verify_auth for dep in [*inherited, *route.dependencies]):
            unprotected.append(path)

    assert unprotected == [], f"routes missing verify_auth: {sorted(set(unprotected))}"


def test_register_requires_api_key(unauthenticated_client: TestClient) -> None:
    """The one-time bootstrap is not an unauthenticated public endpoint."""
    response = unauthenticated_client.post(
        "/auth/register",
        json={"email": "first@example.com", "display_name": "First", "password": "pass1234"},
    )
    assert response.status_code == 401


def test_health_is_public(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/health")
    # Public means no credential is required. The endpoint is 200 only when
    # every dependency is reachable, so a dependency-down 503 is still public.
    assert response.status_code in {200, 503}
    body = response.json()
    assert body["status"] == ("ok" if response.status_code == 200 else "degraded")


def test_auth_verify_requires_a_key(unauthenticated_client: TestClient) -> None:
    assert unauthenticated_client.get("/auth/verify").status_code == 401
    assert unauthenticated_client.get("/auth/verify", headers={"X-API-Key": "wrong"}).status_code == 401
    accepted = unauthenticated_client.get(
        "/auth/verify",
        headers={"X-API-Key": "route-auth-test-key"},
    )
    assert accepted.status_code == 200
    assert accepted.json() == {"ok": True}
