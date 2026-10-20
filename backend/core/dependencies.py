"""FastAPI dependency injection.

Provides auth verification, database sessions, and utility dependencies.
Auth validates against ``settings.api_secret_key`` via ``Authorization: Bearer``
or ``X-API-Key`` header.

Every non-public router is mounted with ``verify_auth`` in ``backend.main``.
Only ``/health``, ``/metrics``, OpenAPI docs, and ``/auth/login`` are reachable
without a credential. ``/auth/register`` and ``/auth/verify`` declare their own
auth dependency.

Fail-closed rules:

* an empty or default ``api_secret_key`` rejects every request with 503;
* comparisons use :func:`secrets.compare_digest`;
* there is no debug-mode bypass.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPBearer, OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import User
from backend.services import user_service
from configs.settings import settings
from database.connection import async_session_factory

security_scheme = HTTPBearer(auto_error=False)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Sentinel for the shipped placeholder. The default is public knowledge, so it
# is treated as "not configured" rather than as a valid credential.
_DEFAULT_SECRET = "changeme_in_production"


def _constant_time_match(candidate: str | None, expected: str) -> bool:
    """Compare two credentials without leaking length/prefix timing."""
    if not candidate or not expected:
        return False
    try:
        return secrets.compare_digest(candidate, expected)
    except TypeError:
        # compare_digest rejects non-ASCII str inputs; credentials are ASCII.
        return False


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def verify_auth(
    token: str | None = Depends(oauth2_scheme),
    api_key: str | None = Depends(api_key_header),
) -> str:
    """Validate authentication via Bearer token (JWT) or X-API-Key header.

    Raises:
        HTTPException: 503 when the server has no usable API key configured
            (fail closed), 401 otherwise.
    """
    configured_key = settings.api_secret_key

    # A default/empty key means the operator has not configured auth. Never
    # accept the shipped placeholder and never fall back to a debug bypass.
    if not configured_key or configured_key == _DEFAULT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "API authentication is not configured. Set API_SECRET_KEY to a "
                "unique non-default value before serving requests."
            ),
        )

    # ── JWT Validation ─────────────────────────────────────────────
    # Only attempt JWT decoding when the JWT secret itself is configured;
    # accepting JWTs signed with the public placeholder would be a bypass.
    jwt_configured = bool(settings.jwt_secret_key) and settings.jwt_secret_key != _DEFAULT_SECRET
    if token and jwt_configured:
        try:
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
            email: str | None = payload.get("sub")
            if email:
                return email
        except JWTError:
            pass  # Fall through to API-key validation.

    # ── API Key Validation (Server-to-Server) ──────────────────────
    if _constant_time_match(token, configured_key):
        return token  # type: ignore[return-value]
    if _constant_time_match(api_key, configured_key):
        return api_key  # type: ignore[return-value]

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key/token. Provide via Authorization: Bearer or X-API-Key header.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_id(
    auth: str = Depends(verify_auth),
) -> str:
    """Extract the current user identifier from auth credentials."""
    return auth


async def get_current_user(auth: str = Depends(verify_auth), db: AsyncSession = Depends(get_db)) -> User:
    """Resolve the current user record from the database."""
    if auth == settings.api_secret_key:
        # Server-to-server API-key callers have no user row.
        raise HTTPException(status_code=403, detail="A real user context is required.")

    user = await user_service.get_by_email(db, auth)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user
