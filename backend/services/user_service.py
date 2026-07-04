"""User service for database operations."""

from __future__ import annotations
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import User
from backend.schemas.user import UserCreate
from backend.core.security import hash_password


async def get_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """Get a user by email."""
    result = await db.execute(select(User).where(User.email == email))
    return result.scalars().first()


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
    """Get a user by ID."""
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalars().first()


async def create_user(db: AsyncSession, user_in: UserCreate) -> User:
    """Create a new user with hashed password."""
    db_user = User(
        email=user_in.email,
        display_name=user_in.display_name,
        password_hash=hash_password(user_in.password),
        role=user_in.role,
        is_active=True
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user
