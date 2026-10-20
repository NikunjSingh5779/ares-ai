from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    email: EmailStr
    display_name: str
    role: str = "user"


class UserCreate(UserBase):
    password: str = Field(min_length=8)


class UserRegister(BaseModel):
    """Public registration payload — deliberately excludes ``role``.

    The first registered account becomes the local operator (admin); later
    registrations are rejected. A client must never be able to choose its own
    role.
    """

    email: EmailStr
    display_name: str
    password: str = Field(min_length=8)


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    display_name: str | None = None
    password: str | None = Field(default=None, min_length=8)
