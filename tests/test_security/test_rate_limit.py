"""Tests for the rate limiting middleware."""
from __future__ import annotations

import time

from starlette.testclient import TestClient


def test_rate_limit_allows_normal_requests() -> None:
    """Verify normal requests pass through rate limiter."""
    from fastapi import FastAPI

    from backend.core.rate_limit import RateLimitMiddleware

    app = FastAPI()

    @app.get("/test-rate")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware, default_limit=100)

    with TestClient(app) as client:
        for _ in range(5):
            resp = client.get("/test-rate")
            assert resp.status_code == 200


def test_rate_limit_allows_health_endpoint() -> None:
    """Verify health endpoint bypasses rate limiting."""
    from fastapi import FastAPI

    from backend.core.rate_limit import RateLimitMiddleware

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.add_middleware(RateLimitMiddleware, default_limit=1)

    with TestClient(app) as client:
        # Exempt endpoint should always pass even with 1/min limit
        for _ in range(10):
            resp = client.get("/health")
            assert resp.status_code == 200


def test_rate_limit_returns_429_when_exceeded() -> None:
    """Verify rate limit returns 429 after exceeding limit."""
    from fastapi import FastAPI

    from backend.core.rate_limit import RateLimitMiddleware

    app = FastAPI()

    @app.post("/test-rate-limited")
    async def test_endpoint():
        return {"ok": True}

    # Set a very low limit for testing
    app.add_middleware(RateLimitMiddleware, default_limit=1)

    with TestClient(app) as client:
        # First request should pass
        resp = client.post("/test-rate-limited")
        assert resp.status_code == 200

        # Second request should be rate limited
        resp = client.post("/test-rate-limited")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers


def test_rate_limit_get_gets_double_limit() -> None:
    """Verify GET endpoints get 2x the default limit."""
    from fastapi import FastAPI

    from backend.core.rate_limit import RateLimitMiddleware

    app = FastAPI()

    @app.get("/get-endpoint")
    async def get_endpoint():
        return {"ok": True}

    # limit=1 means GET gets 2
    app.add_middleware(RateLimitMiddleware, default_limit=1)

    with TestClient(app) as client:
        # Two GET requests should pass
        resp = client.get("/get-endpoint")
        assert resp.status_code == 200
        resp = client.get("/get-endpoint")
        assert resp.status_code == 200

        # Third should be rate limited
        resp = client.get("/get-endpoint")
        assert resp.status_code == 429


def test_rate_limit_resets_after_period(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Verify the token bucket refills over time."""
    from fastapi import FastAPI

    from backend.core.rate_limit import RateLimitMiddleware

    app = FastAPI()

    @app.post("/test-refill")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware, default_limit=1)

    with TestClient(app) as client:
        # Exhaust the bucket
        resp = client.post("/test-refill")
        assert resp.status_code == 200

        resp = client.post("/test-refill")
        assert resp.status_code == 429

    # Fast-forward time to simulate refill
    import backend.core.rate_limit as rl

    original_time = time.monotonic

    try:
        monkeypatch.setattr(
            time, "monotonic", lambda: original_time() + 65
        )

        with TestClient(app) as client:
            resp = client.post("/test-refill")
            assert resp.status_code == 200
    finally:
        monkeypatch.setattr(time, "monotonic", original_time)
