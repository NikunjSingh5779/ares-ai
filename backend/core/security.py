"""Security headers middleware.

Adds security-related HTTP headers to every response:
- Content-Security-Policy
- Strict-Transport-Security
- X-Content-Type-Options
- X-Frame-Options
- Referrer-Policy
- Permissions-Policy
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    CSP_DEFAULT = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://js.stripe.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' http://localhost:8000 ws://localhost:8000; "
        "frame-src 'none'; "
        "object-src 'none'; "
        "base-uri 'self'"
    )

    HEADERS = {
        "Content-Security-Policy": CSP_DEFAULT,
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }

    async def dispatch(self, request: Request, call_next: callable) -> Response:  # type: ignore[type-arg]
        response = await call_next(request)
        for header, value in self.HEADERS.items():
            response.headers[header] = value
        return response
