"""In-process rate limiting middleware.

Uses a simple token-bucket algorithm per endpoint.
Configured via ``settings.api_rate_limit_per_minute``.

POST endpoints get the default limit; GET endpoints get 2x.
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class TokenBucket:
    """Simple token bucket for rate limiting."""

    def __init__(self, rate_per_minute: int) -> None:
        self.capacity = rate_per_minute
        self.tokens = float(rate_per_minute)
        self.refill_rate = rate_per_minute / 60.0  # tokens per second
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        """Try to consume one token. Returns ``True`` if allowed."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limit requests per endpoint based on HTTP method.

    POST endpoints are limited to ``default_limit`` per minute.
    GET endpoints get 2x the limit.
    """

    def __init__(self, app, default_limit: int = 100) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._buckets: dict[str, TokenBucket] = {}
        self._default_limit = default_limit

    def _get_limit(self, method: str) -> int:
        if method == "GET":
            return self._default_limit * 2
        return self._default_limit

    async def dispatch(self, request: Request, call_next: callable) -> Response:  # type: ignore[type-arg]
        # Skip rate limiting for health, metrics, docs
        path = request.url.path
        if path in ("/health", "/", "/metrics", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        key = f"{request.method}:{path}"
        limit = self._get_limit(request.method)

        if key not in self._buckets:
            self._buckets[key] = TokenBucket(limit)

        bucket = self._buckets[key]
        if not bucket.consume():
            return Response(
                status_code=429,
                content='{"detail":"Rate limit exceeded. Please slow down."}',
                media_type="application/json",
                headers={"Retry-After": "60"},
            )

        return await call_next(request)
