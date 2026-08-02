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

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import jwt
from passlib.context import CryptContext
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from configs.settings import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return pwd_context.hash(password)  # type: ignore[no-any-return]


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)  # type: ignore[no-any-return]


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return encoded_jwt  # type: ignore[no-any-return]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response.

    ``Content-Security-Policy`` is built per-request from
    ``settings.csp_connect_src`` so that configuration changes are
    reflected immediately and the component is testable via
    monkey-patching.  All other headers are static.
    """

    # Static headers — built once at class body time since they
    # don't depend on runtime settings.
    _STATIC_HEADERS: dict[str, str] = {
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }

    @staticmethod
    def _build_csp_header() -> str:
        """Build the Content-Security-Policy value from current settings.

        Called on every request so that a settings change (e.g. a test
        monkey-patch or a future dynamic-config mechanism) is reflected
        immediately.
        """
        return (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            f"connect-src 'self' {settings.csp_connect_src}; "
            "frame-src 'none'; "
            "object-src 'none'; "
            "base-uri 'self'"
        )

    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = self._build_csp_header()
        for header, value in self._STATIC_HEADERS.items():
            response.headers[header] = value
        return response  # type: ignore[no-any-return]
