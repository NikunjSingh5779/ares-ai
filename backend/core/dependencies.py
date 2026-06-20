"""FastAPI dependency injection.

Provides auth verification, database sessions, and utility dependencies.
Auth validates against ``settings.api_secret_key`` via ``Authorization: Bearer``
or ``X-API-Key`` header.

Public endpoints (health, docs, root) do not use ``verify_auth``;
all trading and live POST endpoints require it.
"""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from configs.settings import settings
from database.connection import async_session_factory

security_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Sentinel for default key — if still set, debug-mode bypass is allowed
_DEFAULT_SECRET = "changeme_in_production"


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
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    api_key: str | None = Depends(api_key_header),
) -> str:
    """Validate authentication via Bearer token or X-API-Key header.

    In debug mode with the default secret key, any non-empty credential is
    accepted for development convenience.

    In production (non-default secret key), the credential must match
    ``settings.api_secret_key`` exactly.
    """
    # ── Debug mode with default key: accept anything ──────────────
    if settings.api_debug and settings.api_secret_key == _DEFAULT_SECRET:
        if credentials:
            return credentials.credentials
        if api_key:
            return api_key
        return "dev-user-id"

    # ── Production: validate against api_secret_key ───────────────
    token: str | None = None
    if credentials:
        token = credentials.credentials
    elif api_key:
        token = api_key

    if token is not None and token == settings.api_secret_key:
        return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key. Provide via Authorization: Bearer or X-API-Key header.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_id(
    auth: str = Depends(verify_auth),
) -> str:
    """Extract the current user identifier from auth credentials.

    In production this will resolve the token to a user record from the
    users table. For now it returns the raw credential value.
    """
    return auth
