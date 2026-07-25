"""Users router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_current_user, get_db
from backend.db.models import User
from backend.schemas.user import UserResponse
from backend.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def read_own_profile(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Get the current authenticated user's profile."""
    return current_user  # type: ignore[return-value]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> UserResponse:
    """Get a specific user by ID. Only admins can fetch arbitrary users."""
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

    user = await user_service.get_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user  # type: ignore[return-value]
