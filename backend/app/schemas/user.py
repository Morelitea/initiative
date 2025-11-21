from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr

from app.models.user import UserRole


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    role: UserRole = UserRole.member


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    avatar_base64: Optional[str] = None
    avatar_url: Optional[str] = None


class UserRead(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    avatar_base64: Optional[str] = None
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True


class UserInDB(UserRead):
    hashed_password: str


class UserSelfUpdate(BaseModel):
    full_name: Optional[str] = None
    password: Optional[str] = None
    avatar_base64: Optional[str] = None
    avatar_url: Optional[str] = None
