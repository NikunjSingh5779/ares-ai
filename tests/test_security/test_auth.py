"""Tests for auth dependency hardening."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient


def _make_app(debug: bool = False, secret_key: str = "changeme_in_production") -> FastAPI:
    """Helper to create a test app with auth dependency."""
    from configs.settings import Settings

    app = FastAPI()
    app.state.settings = Settings(
        api_debug=debug,
        api_secret_key=secret_key,
    )

    return app


def _patch_settings(app: FastAPI, **kwargs) -> None:  # type: ignore[no-untyped-def]
    """Patch settings for the test app."""
    import configs.settings as settings_module

    for key, value in kwargs.items():
        setattr(settings_module.settings, key, value)


class TestVerifyAuth:
    """Tests for the verify_auth dependency."""

    def test_debug_mode_no_auth(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """In debug mode with default key, requests without auth get a dev user."""
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from backend.core.dependencies import verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_debug", True)
        monkeypatch.setattr(settings, "api_secret_key", "changeme_in_production")

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            resp = client.get("/protected")
            assert resp.status_code == 200
            assert resp.json()["user"] == "dev-user-id"

    def test_debug_mode_with_bearer_token(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """In debug mode, a bearer token is accepted."""
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from backend.core.dependencies import verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_debug", True)
        monkeypatch.setattr(settings, "api_secret_key", "changeme_in_production")

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            resp = client.get("/protected", headers={"Authorization": "Bearer my-token"})
            assert resp.status_code == 200
            assert resp.json()["user"] == "my-token"

    def test_debug_mode_with_api_key(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """In debug mode, an X-API-Key header is accepted."""
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from backend.core.dependencies import verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_debug", True)
        monkeypatch.setattr(settings, "api_secret_key", "changeme_in_production")

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            resp = client.get("/protected", headers={"X-API-Key": "my-api-key"})
            assert resp.status_code == 200
            assert resp.json()["user"] == "my-api-key"

    def test_production_requires_auth(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """In production mode, requests without auth return 401."""
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from backend.core.dependencies import verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_debug", False)
        monkeypatch.setattr(settings, "api_secret_key", "prod-secret-key")

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            resp = client.get("/protected")
            assert resp.status_code == 401

    def test_production_accepts_bearer_token(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """In production mode, a valid bearer token is accepted."""
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from backend.core.dependencies import verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_debug", False)
        monkeypatch.setattr(settings, "api_secret_key", "prod-secret-key")

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            resp = client.get(
                "/protected",
                headers={"Authorization": "Bearer prod-secret-key"},
            )
            assert resp.status_code == 200
            assert resp.json()["user"] == "prod-secret-key"

    def test_production_accepts_api_key(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """In production mode, a valid X-API-Key header is accepted."""
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from backend.core.dependencies import verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_debug", False)
        monkeypatch.setattr(settings, "api_secret_key", "prod-secret-key")

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            resp = client.get(
                "/protected",
                headers={"X-API-Key": "prod-secret-key"},
            )
            assert resp.status_code == 200
            assert resp.json()["user"] == "prod-secret-key"

    def test_production_rejects_wrong_key(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """In production mode, a wrong key returns 401."""
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from backend.core.dependencies import verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_debug", False)
        monkeypatch.setattr(settings, "api_secret_key", "prod-secret-key")

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            resp = client.get(
                "/protected",
                headers={"Authorization": "Bearer wrong-key"},
            )
            assert resp.status_code == 401

    def test_production_rejects_wrong_api_key(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """In production mode, a wrong X-API-Key returns 401."""
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from backend.core.dependencies import verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_debug", False)
        monkeypatch.setattr(settings, "api_secret_key", "prod-secret-key")

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            resp = client.get(
                "/protected",
                headers={"X-API-Key": "wrong-key"},
            )
            assert resp.status_code == 401

    def test_get_current_user_id(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """Verify get_current_user_id extracts the credential."""
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from backend.core.dependencies import get_current_user_id, verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_debug", False)
        monkeypatch.setattr(settings, "api_secret_key", "test-key")

        app = FastAPI()

        @app.get("/me")
        async def me(user: str = Depends(get_current_user_id)):
            return {"user_id": user}

        with TestClient(app) as client:
            resp = client.get("/me", headers={"Authorization": "Bearer test-key"})
            assert resp.status_code == 200
            assert resp.json()["user_id"] == "test-key"
