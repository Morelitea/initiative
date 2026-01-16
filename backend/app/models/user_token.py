from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, String
from sqlmodel import Enum as SQLEnum, Field, SQLModel


class UserTokenPurpose(str, Enum):
    email_verification = "email_verification"
    password_reset = "password_reset"
    device_auth = "device_auth"  # Long-lived device tokens for mobile apps


class UserToken(SQLModel, table=True):
    __tablename__ = "user_tokens"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    token: str = Field(
        sa_column=Column(String(128), nullable=False, unique=True, index=True),
    )
    purpose: UserTokenPurpose = Field(
        sa_column=Column(
            SQLEnum(UserTokenPurpose, name="user_token_purpose", create_type=False),
            nullable=False,
        ),
    )
    # Device name for device_auth tokens (e.g., "John's iPhone")
    device_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    consumed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
