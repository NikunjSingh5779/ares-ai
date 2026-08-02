"""Tests for global ARES AI exception handlers."""

from __future__ import annotations

from starlette.testclient import TestClient

from backend.core.exceptions import AresError, AuthenticationError, ConfigurationError, RateLimitError


class TestAresErrorHandler:
    """Exception-to-status-code mapping for each error type."""

    def test_ares_error_defaults_to_400(self) -> None:
        """A plain AresError should return 400."""
        from fastapi import FastAPI

        from backend.core.error_handlers import ares_error_handler
        from backend.core.exceptions import AresError

        app = FastAPI()

        @app.get("/test-ares-error")
        async def test_endpoint():
            raise AresError("generic domain error")

        app.add_exception_handler(AresError, ares_error_handler)

        with TestClient(app) as client:
            resp = client.get("/test-ares-error")
            assert resp.status_code == 400
            assert resp.json()["detail"] == "generic domain error"

    def test_authentication_error_returns_401(self) -> None:
        """AuthenticationError should return 401."""
        from fastapi import FastAPI

        from backend.core.error_handlers import ares_error_handler

        app = FastAPI()

        @app.get("/test-auth-error")
        async def test_endpoint():
            raise AuthenticationError("not authenticated")

        app.add_exception_handler(AresError, ares_error_handler)

        with TestClient(app) as client:
            resp = client.get("/test-auth-error")
            assert resp.status_code == 401

    def test_rate_limit_error_returns_429(self) -> None:
        """RateLimitError should return 429."""
        from fastapi import FastAPI

        from backend.core.error_handlers import ares_error_handler

        app = FastAPI()

        @app.get("/test-rate-limit")
        async def test_endpoint():
            raise RateLimitError("too many requests")

        app.add_exception_handler(AresError, ares_error_handler)

        with TestClient(app) as client:
            resp = client.get("/test-rate-limit")
            assert resp.status_code == 429

    def test_configuration_error_returns_500(self) -> None:
        """ConfigurationError should return 500."""
        from fastapi import FastAPI

        from backend.core.error_handlers import ares_error_handler

        app = FastAPI()

        @app.get("/test-config-error")
        async def test_endpoint():
            raise ConfigurationError("misconfigured")

        app.add_exception_handler(AresError, ares_error_handler)

        with TestClient(app) as client:
            resp = client.get("/test-config-error")
            assert resp.status_code == 500
