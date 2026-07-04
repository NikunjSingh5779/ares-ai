"""FastAPI dependency injection.

Provides auth verification, database sessions, and utility dependencies.
Auth validates against ``settings.api_secret_key`` via ``Authorization: Bearer``
or ``X-API-Key`` header.

Public endpoints (health, docs, root) do not use ``verify_auth``;
all trading and live POST endpoints require it.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from configs.settings import settings
from database.connection import async_session_factory
from backend.db.models import User
from backend.services import user_service

security_scheme = HTTPBearer(auto_error=False)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)
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
    token: str | None = Depends(oauth2_scheme),
    api_key: str | None = Depends(api_key_header),
) -> str:
    """Validate authentication via Bearer token (JWT) or X-API-Key header."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # ── Debug mode with default key: accept anything ──────────────
    if settings.api_debug and settings.api_secret_key == _DEFAULT_SECRET:
        if token:
            return token
        if api_key:
            return api_key
        return "dev-user-id"

    # ── JWT Validation ───────────────
    if token:
        try:
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
            email: str | None = payload.get("sub")
            if email is None:
                raise credentials_exception
            return email
        except JWTError:
            pass # Fallback to api key if JWT fails

    # ── API Key Validation (Server-to-Server) ───────────────
    if token == settings.api_secret_key:
        return token
    if api_key and api_key == settings.api_secret_key:
        return api_key

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


async def get_current_user(
    auth: str = Depends(verify_auth),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Resolve the current user record from the database."""
    if auth == settings.api_secret_key or auth == "dev-user-id":
        # Server-to-server or dev mode fallback
        raise HTTPException(status_code=403, detail="A real user context is required.")
        
    user = await user_service.get_by_email(db, auth)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user
