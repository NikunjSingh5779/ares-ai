"""Tests for the security headers middleware."""
from __future__ import annotations

from starlette.testclient import TestClient


def test_security_headers_present() -> None:
    """Verify all expected security headers are on every response."""
    from fastapi import FastAPI

    from backend.core.security import SecurityHeadersMiddleware

    app = FastAPI()

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(SecurityHeadersMiddleware)

    expected_headers = {
        "content-security-policy",
        "strict-transport-security",
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
        "permissions-policy",
    }

    with TestClient(app) as client:
        resp = client.get("/test")
        assert resp.status_code == 200

        for header in expected_headers:
            assert header in resp.headers, f"Missing header: {header}"


def test_content_security_policy_default() -> None:
    """Verify Content-Security-Policy header has correct value."""
    from fastapi import FastAPI

    from backend.core.security import SecurityHeadersMiddleware

    app = FastAPI()

    @app.get("/test-csp")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(SecurityHeadersMiddleware)

    with TestClient(app) as client:
        resp = client.get("/test-csp")
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "style-src 'self'" in csp
        assert "frame-src 'none'" in csp
        assert "object-src 'none'" in csp
        assert "base-uri 'self'" in csp


def test_hsts_header() -> None:
    """Verify Strict-Transport-Security header is present and correct."""
    from fastapi import FastAPI

    from backend.core.security import SecurityHeadersMiddleware

    app = FastAPI()

    @app.get("/test-hsts")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(SecurityHeadersMiddleware)

    with TestClient(app) as client:
        resp = client.get("/test-hsts")
        hsts = resp.headers.get("strict-transport-security", "")
        assert "max-age=31536000" in hsts
        assert "includeSubDomains" in hsts
        assert "preload" in hsts


def test_x_content_type_options() -> None:
    """Verify X-Content-Type-Options header is nosniff."""
    from fastapi import FastAPI

    from backend.core.security import SecurityHeadersMiddleware

    app = FastAPI()

    @app.get("/test-xcto")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(SecurityHeadersMiddleware)

    with TestClient(app) as client:
        resp = client.get("/test-xcto")
        assert resp.headers.get("x-content-type-options") == "nosniff"


def test_x_frame_options() -> None:
    """Verify X-Frame-Options header is DENY."""
    from fastapi import FastAPI

    from backend.core.security import SecurityHeadersMiddleware

    app = FastAPI()

    @app.get("/test-xfo")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(SecurityHeadersMiddleware)

    with TestClient(app) as client:
        resp = client.get("/test-xfo")
        assert resp.headers.get("x-frame-options") == "DENY"


def test_referrer_policy() -> None:
    """Verify Referrer-Policy header is correct."""
    from fastapi import FastAPI

    from backend.core.security import SecurityHeadersMiddleware

    app = FastAPI()

    @app.get("/test-referrer")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(SecurityHeadersMiddleware)

    with TestClient(app) as client:
        resp = client.get("/test-referrer")
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_permissions_policy() -> None:
    """Verify Permissions-Policy header restricts camera, mic, geolocation."""
    from fastapi import FastAPI

    from backend.core.security import SecurityHeadersMiddleware

    app = FastAPI()

    @app.get("/test-permissions")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(SecurityHeadersMiddleware)

    with TestClient(app) as client:
        resp = client.get("/test-permissions")
        pp = resp.headers.get("permissions-policy", "")
        assert "camera=()" in pp
        assert "microphone=()" in pp
        assert "geolocation=()" in pp
