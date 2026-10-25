"""Tests for auth dependency hardening."""

from __future__ import annotations

from fastapi import FastAPI
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


def _patch_settings(app: FastAPI, **kwargs) -> None:
    """Patch settings for the test app."""
    import configs.settings as settings_module

    for key, value in kwargs.items():
        setattr(settings_module.settings, key, value)


class TestVerifyAuth:
    """Tests for the verify_auth dependency."""

    def test_debug_mode_does_not_bypass_auth(self, monkeypatch) -> None:
        """API_DEBUG must never turn missing credentials into a dev user."""
        from fastapi import Depends, FastAPI

        from backend.core.dependencies import verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_debug", True)
        monkeypatch.setattr(settings, "api_secret_key", "prod-secret-key")

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            resp = client.get("/protected")
            assert resp.status_code == 401

    def test_debug_mode_rejects_arbitrary_bearer_token(self, monkeypatch) -> None:
        """A random bearer token is not accepted just because debug is on."""
        from fastapi import Depends, FastAPI

        from backend.core.dependencies import verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_debug", True)
        monkeypatch.setattr(settings, "api_secret_key", "prod-secret-key")

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            resp = client.get("/protected", headers={"Authorization": "Bearer my-token"})
            assert resp.status_code == 401

    def test_debug_mode_rejects_arbitrary_api_key(self, monkeypatch) -> None:
        """A random X-API-Key is not accepted just because debug is on."""
        from fastapi import Depends, FastAPI

        from backend.core.dependencies import verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_debug", True)
        monkeypatch.setattr(settings, "api_secret_key", "prod-secret-key")

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            resp = client.get("/protected", headers={"X-API-Key": "my-api-key"})
            assert resp.status_code == 401

    def test_default_key_fails_closed(self, monkeypatch) -> None:
        """The shipped placeholder is treated as unconfigured (503)."""
        from fastapi import Depends, FastAPI

        from backend.core.dependencies import verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_debug", False)
        monkeypatch.setattr(settings, "api_secret_key", "changeme_in_production")

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            assert client.get("/protected").status_code == 503
            assert client.get("/protected", headers={"X-API-Key": "changeme_in_production"}).status_code == 503

    def test_empty_key_fails_closed(self, monkeypatch) -> None:
        """An empty API key rejects every request instead of matching empty input."""
        from fastapi import Depends, FastAPI

        from backend.core.dependencies import verify_auth
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_secret_key", "")

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            assert client.get("/protected").status_code == 503
            assert client.get("/protected", headers={"X-API-Key": ""}).status_code == 503

    def test_production_requires_auth(self, monkeypatch) -> None:
        """In production mode, requests without auth return 401."""
        from fastapi import Depends, FastAPI

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

    def test_production_accepts_bearer_token(self, monkeypatch) -> None:
        """In production mode, a valid bearer token is accepted."""
        from fastapi import Depends, FastAPI

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

    def test_production_accepts_api_key(self, monkeypatch) -> None:
        """In production mode, a valid X-API-Key header is accepted."""
        from fastapi import Depends, FastAPI

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

    def test_production_rejects_wrong_key(self, monkeypatch) -> None:
        """In production mode, a wrong key returns 401."""
        from fastapi import Depends, FastAPI

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

    def test_production_rejects_wrong_api_key(self, monkeypatch) -> None:
        """In production mode, a wrong X-API-Key returns 401."""
        from fastapi import Depends, FastAPI

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

    def test_jwt_signed_with_default_secret_is_rejected(self, monkeypatch) -> None:
        """A JWT signed with the public placeholder must never authenticate."""
        from fastapi import Depends, FastAPI

        from backend.core.dependencies import verify_auth
        from backend.core.security import create_access_token
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_secret_key", "prod-secret-key")
        monkeypatch.setattr(settings, "jwt_secret_key", "changeme_in_production")
        token = create_access_token({"sub": "attacker@example.com"})

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 401

    def test_jwt_is_accepted_when_jwt_secret_is_configured(self, monkeypatch) -> None:
        """A JWT signed with a configured secret resolves to its subject."""
        from fastapi import Depends, FastAPI

        from backend.core.dependencies import verify_auth
        from backend.core.security import create_access_token
        from configs.settings import settings

        monkeypatch.setattr(settings, "api_secret_key", "prod-secret-key")
        monkeypatch.setattr(settings, "jwt_secret_key", "real-jwt-secret")
        token = create_access_token({"sub": "operator@example.com"})

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: str = Depends(verify_auth)):
            return {"user": user}

        with TestClient(app) as client:
            resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200
            assert resp.json()["user"] == "operator@example.com"

    def test_get_current_user_id(self, monkeypatch) -> None:
        """Verify get_current_user_id extracts the credential."""
        from fastapi import Depends, FastAPI

        from backend.core.dependencies import get_current_user_id
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
