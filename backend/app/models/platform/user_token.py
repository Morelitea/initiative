from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlmodel import Enum as SQLEnum, Field, SQLModel


class UserTokenPurpose(str, Enum):
    email_verification = "email_verification"
    password_reset = "password_reset"


class UserToken(SQLModel, table=True):
    __tablename__ = "user_tokens"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(
        foreign_key="users.id", ondelete="CASCADE", nullable=False, index=True
    )
    token: str = Field(
        sa_column=Column(String(128), nullable=False, unique=True, index=True),
    )
    purpose: UserTokenPurpose = Field(
        sa_column=Column(
            SQLEnum(UserTokenPurpose, name="user_token_purpose", create_type=False),
            nullable=False,
        ),
    )
    # Which address an email_verification token proves. NULL for the flows that
    # name the account rather than one of its addresses.
    user_email_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("user_emails.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    # The invite a sign-up joins once this token proves its address. NULL for
    # every other token.
    invite_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("guild_invites.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
