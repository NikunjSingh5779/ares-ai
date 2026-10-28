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

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from configs.settings import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# A trade approval token is deliberately distinct from a login access token.
# The ``typ``/``aud``/``iss`` claims make an access token unusable here and a
# stolen approval token unusable on normal authenticated routes.
APPROVAL_TOKEN_TYPE = "trade_approval"
APPROVAL_TOKEN_ISSUER = "ares-ai"
APPROVAL_TOKEN_AUDIENCE = "paper-execute"
_DEFAULT_JWT_SECRET = "changeme_in_production"


class ApprovalTokenError(ValueError):
    """Raised when a trade approval token cannot be issued or verified."""


@dataclass(frozen=True)
class IssuedApprovalToken:
    """A freshly signed approval token and its server-side expiry."""

    token: str
    expires_at: datetime


@dataclass(frozen=True)
class TradeApprovalClaims:
    """Verified claims from a trade approval token."""

    symbol: str
    side: str
    approval_hash: str
    jti: str
    expires_at: datetime


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return pwd_context.hash(password)  # type: ignore[no-any-return]


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)  # type: ignore[no-any-return]


def _approval_signing_key() -> str:
    """Return the JWT signing key, refusing the public placeholder.

    An approval token signed with the shipped default would be forgeable by
    anyone, so issuance and verification both fail closed until an operator
    sets a unique ``JWT_SECRET_KEY``.
    """
    key = settings.jwt_secret_key
    if not key or key == _DEFAULT_JWT_SECRET:
        raise ApprovalTokenError("JWT_SECRET_KEY is not configured; trade approval tokens cannot be signed")
    return key


def approval_payload_hash(approval: BaseModel | dict[str, Any]) -> str:
    """Return a canonical SHA-256 digest of an approval payload.

    The digest is computed over sorted, compact JSON so two equivalent Pydantic
    models produce the same value regardless of field or dictionary order.
    """
    payload = approval.model_dump(mode="json") if isinstance(approval, BaseModel) else approval
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_trade_approval_token(
    *,
    symbol: str,
    side: str,
    approval: BaseModel | dict[str, Any],
    expires_delta: timedelta | None = None,
) -> IssuedApprovalToken:
    """Sign a short-lived approval token bound to one agent payload.

    Args:
        symbol: The exact symbol the approval was generated for.
        side: ``long`` or ``short``.
        approval: The typed Market Analyst/Quant/Risk payload. Only its digest
            is embedded; the caller must submit the payload with the token.
        expires_delta: Override the configured lifetime (tests use this).

    Raises:
        ApprovalTokenError: If the JWT signing key is missing or default.
    """
    key = _approval_signing_key()
    now = datetime.now(UTC)
    lifetime = expires_delta if expires_delta is not None else timedelta(minutes=settings.approval_token_expire_minutes)
    expires_at = (now + lifetime).replace(microsecond=0)
    claims = {
        "typ": APPROVAL_TOKEN_TYPE,
        "iss": APPROVAL_TOKEN_ISSUER,
        "aud": APPROVAL_TOKEN_AUDIENCE,
        "iat": now,
        "exp": expires_at,
        "jti": str(uuid.uuid4()),
        "symbol": symbol,
        "side": side,
        "approval_hash": approval_payload_hash(approval),
    }
    token = jwt.encode(claims, key, algorithm=settings.jwt_algorithm)
    return IssuedApprovalToken(token=token, expires_at=expires_at)


def verify_trade_approval_token(token: str) -> TradeApprovalClaims:
    """Verify a trade approval token and return its bound claims.

    Raises:
        ApprovalTokenError: If the token is missing, expired, signed with the
            wrong key, or has the wrong type/audience/issuer/claims.
    """
    key = _approval_signing_key()
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[settings.jwt_algorithm],
            audience=APPROVAL_TOKEN_AUDIENCE,
            issuer=APPROVAL_TOKEN_ISSUER,
        )
    except JWTError as exc:
        raise ApprovalTokenError("Approval token is invalid or expired") from exc

    if claims.get("typ") != APPROVAL_TOKEN_TYPE:
        raise ApprovalTokenError("Token is not a trade approval token")

    symbol = claims.get("symbol")
    side = claims.get("side")
    approval_hash = claims.get("approval_hash")
    jti = claims.get("jti")
    expires_at = claims.get("exp")

    if not isinstance(symbol, str) or not symbol:
        raise ApprovalTokenError("Approval token has no symbol")
    if side not in {"long", "short"}:
        raise ApprovalTokenError("Approval token has no valid side")
    if not isinstance(approval_hash, str) or len(approval_hash) != 64:
        raise ApprovalTokenError("Approval token has no valid payload hash")
    if not isinstance(jti, str) or not jti:
        raise ApprovalTokenError("Approval token has no identifier")
    if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
        raise ApprovalTokenError("Approval token has no expiry")

    return TradeApprovalClaims(
        symbol=symbol,
        side=side,
        approval_hash=approval_hash,
        jti=jti,
        expires_at=datetime.fromtimestamp(float(expires_at), tz=UTC),
    )


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
