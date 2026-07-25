"""Authentication router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.core.login_rate_limit import login_rate_limiter
from backend.core.security import create_access_token, verify_password
from backend.schemas.user import UserCreate, UserResponse
from backend.services import user_service
from configs.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> UserResponse:
    """Register a new user."""
    existing_user = await user_service.get_by_email(db, payload.email)
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    return await user_service.create_user(db, payload)  # type: ignore[return-value]


@router.post("/login")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Authenticate a user and return a JWT token.

    Rate-limited before password verification to prevent brute-force
    enumeration.  Returns a generic ``429 Too Many Requests`` when the
    narrow (email + IP) or wide (IP-only) limit is exceeded.
    """
    # ── Brute-force throttle (checked BEFORE password verification) ──
    client_ip = login_rate_limiter.get_client_ip(
        request, trusted_proxies=settings.trusted_proxies
    )
    blocked = login_rate_limiter.check_and_record(form_data.username, client_ip)
    if blocked:
        retry_after_sec = int(login_rate_limiter.retry_after(form_data.username, client_ip))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after_sec)},
        )

    user = await user_service.get_by_email(db, form_data.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}
