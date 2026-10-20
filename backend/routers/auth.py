"""Authentication router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db, verify_auth
from backend.core.login_rate_limit import login_rate_limiter
from backend.core.security import create_access_token, verify_password
from backend.schemas.user import UserCreate, UserRegister, UserResponse
from backend.services import user_service
from configs.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserRegister,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_auth),
) -> UserResponse:
    """Create the single local operator account.

    Registration is a one-time bootstrap and requires the operator's
    ``X-API-Key``. Once any user exists, further registration is closed. The
    first account is the local admin. Clients cannot choose their own role —
    ``UserRegister`` has no ``role`` field, and the server assigns it.
    """
    if await user_service.count_users(db) > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Registration is closed. This is a single-user local deployment. Log in with the existing account."
            ),
        )

    existing_user = await user_service.get_by_email(db, payload.email)
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    create_payload = UserCreate(
        email=payload.email,
        display_name=payload.display_name,
        password=payload.password,
        role="admin",
    )
    return await user_service.create_user(db, create_payload)  # type: ignore[return-value]


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
    client_ip = login_rate_limiter.get_client_ip(request, trusted_proxies=settings.trusted_proxies)
    blocked = login_rate_limiter.check_and_record(form_data.username, client_ip)
    if blocked:
        retry_after_sec = int(login_rate_limiter.retry_after(form_data.username, client_ip))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after_sec)},
        )

    # ── JWT availability ──────────────────────────────────────────────
    # Never issue a token that verify_auth will reject. When the JWT secret is
    # unset/default, the API-key path is the only supported login method.
    if not settings.jwt_secret_key or settings.jwt_secret_key == "changeme_in_production":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "JWT login is not configured. Set JWT_SECRET_KEY to a unique "
                "value, or authenticate with the X-API-Key header."
            ),
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


@router.get("/verify")
async def verify_credentials(_: str = Depends(verify_auth)) -> dict[str, bool]:
    """Confirm that the supplied API key or JWT is valid.

    Used by the local dashboard login screen; it deliberately returns no
    identity information beyond ``ok``.
    """
    return {"ok": True}
