"""Role-based authorization for trading and live controls (P1.6).

The unit app proves the role matrix directly. The real-app tests remove the
domain-test overrides and prove the viewer gate is wired onto the actual
trading/live-control routes.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from jose import jwt

from backend.core.dependencies import (
    require_live_control,
    require_trading_access,
    verify_auth,
)
from backend.core.security import create_access_token
from backend.main import app as main_app
from configs.settings import settings

_API_KEY = "role-test-key"
_JWT_SECRET = "role-test-jwt"


def _token(role: str | None, *, subject: str = "role-test@example.com") -> str:
    data: dict[str, Any] = {"sub": subject}
    if role is not None:
        data["role"] = role
    return create_access_token(data)


@pytest.fixture
def role_app(monkeypatch) -> FastAPI:
    """A minimal app with the two role dependencies and no route side effects."""
    monkeypatch.setattr(settings, "api_secret_key", _API_KEY)
    monkeypatch.setattr(settings, "jwt_secret_key", _JWT_SECRET)

    app = FastAPI()

    @app.get("/trade", dependencies=[Depends(require_trading_access)])
    async def trade() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/live", dependencies=[Depends(require_live_control)])
    async def live() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.mark.parametrize(
    ("role", "trade_status", "live_status"),
    [
        ("viewer", 403, 403),
        ("user", 200, 200),  # legacy alias for operator
        ("operator", 200, 200),
        ("admin", 200, 200),
        ("super_admin", 200, 200),
        ("not-a-role", 403, 403),  # unknown roles fail closed
    ],
)
def test_role_matrix(role_app: FastAPI, role: str, trade_status: int, live_status: int) -> None:
    headers = {"Authorization": f"Bearer {_token(role)}"}
    with TestClient(role_app) as client:
        assert client.get("/trade", headers=headers).status_code == trade_status
        assert client.get("/live", headers=headers).status_code == live_status


def test_token_without_role_is_read_only(role_app: FastAPI) -> None:
    headers = {"Authorization": f"Bearer {_token(None)}"}
    with TestClient(role_app) as client:
        assert client.get("/trade", headers=headers).status_code == 403
        assert client.get("/live", headers=headers).status_code == 403


def test_api_key_is_operator_trust_boundary(role_app: FastAPI) -> None:
    with TestClient(role_app) as client:
        assert client.get("/trade", headers={"X-API-Key": _API_KEY}).status_code == 200
        assert client.get("/live", headers={"X-API-Key": _API_KEY}).status_code == 200
        assert client.get("/trade", headers={"Authorization": f"Bearer {_API_KEY}"}).status_code == 200


def test_invalid_token_is_rejected(role_app: FastAPI) -> None:
    with TestClient(role_app) as client:
        assert client.get("/trade", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
        assert client.get("/live", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_login_token_carries_the_role(role_app: FastAPI) -> None:
    token = _token("viewer")
    payload = jwt.decode(token, _JWT_SECRET, algorithms=[settings.jwt_algorithm])
    assert payload["role"] == "viewer"


def test_real_routes_declare_role_dependencies() -> None:
    required: dict[str, Any] = {
        "/api/v1/execute": require_trading_access,
        "/api/v1/live/mode": require_live_control,
        "/api/v1/live/start": require_live_control,
        "/api/v1/live/stop": require_live_control,
        "/api/v1/live/kill": require_live_control,
        "/api/v1/live/arm": require_live_control,
    }
    routes = {}
    for route in main_app.routes:
        children = getattr(getattr(route, "original_router", None), "routes", None)
        for child in children if children is not None else [route]:
            if isinstance(child, APIRoute):
                routes[child.path] = child
    for path, dependency in required.items():
        assert path in routes, f"{path} is not mounted"
        assert any(candidate.dependency is dependency for candidate in routes[path].dependencies), (
            f"{path} is missing its role dependency"
        )


@pytest.fixture
def real_app_without_overrides(monkeypatch) -> Iterator[FastAPI]:
    """Clear the domain-test auth overrides so the real gates run."""
    monkeypatch.setattr(settings, "api_secret_key", _API_KEY)
    monkeypatch.setattr(settings, "jwt_secret_key", _JWT_SECRET)
    dependencies = (verify_auth, require_trading_access, require_live_control)
    saved = {dependency: main_app.dependency_overrides.pop(dependency, None) for dependency in dependencies}
    try:
        yield main_app
    finally:
        for dependency, override in saved.items():
            if override is not None:
                main_app.dependency_overrides[dependency] = override


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/execute", {}),
        ("/api/v1/live/mode", {"mode": "paper"}),
        ("/api/v1/live/start", None),
        ("/api/v1/live/stop", None),
        ("/api/v1/live/kill", {"reason": "test"}),
        ("/api/v1/live/arm", None),
    ],
)
def test_viewer_cannot_trade_or_control_live(
    real_app_without_overrides: FastAPI, path: str, payload: dict[str, Any] | None
) -> None:
    headers = {"Authorization": f"Bearer {_token('viewer')}"}
    response = TestClient(real_app_without_overrides).post(path, json=payload, headers=headers)
    assert response.status_code == 403, f"{path} returned {response.status_code}: {response.text}"


def test_operator_passes_the_role_gate(real_app_without_overrides: FastAPI) -> None:
    """An operator reaches body validation instead of being forbidden."""
    headers = {"Authorization": f"Bearer {_token('operator')}"}
    response = TestClient(real_app_without_overrides).post("/api/v1/execute", json={}, headers=headers)
    assert response.status_code == 422
