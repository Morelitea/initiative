from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Enum as SQLEnum, Field, SQLModel


class UserTokenPurpose(str, Enum):
    email_verification = "email_verification"
    password_reset = "password_reset"
    device_auth = "device_auth"  # Long-lived device tokens for mobile apps


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
    # Device name for device_auth tokens (e.g., "John's iPhone")
    device_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    # What the sign-in that minted a device_auth token recorded about itself.
    # A relay sign-in hands the app a token instead of opening a session, and
    # this is how that sign-in's own account of itself reaches the session the
    # app trades the token for.
    amr: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text("'{}'")),
    )
    # When the exchange took it. The markers above are the sign-in's, and the
    # exchange that carries them into a session is the rest of that sign-in;
    # every exchange after it is the app resuming, which proves nothing new. So
    # they are handed over once, and a token that has never been traded stops
    # offering them after ``DEVICE_TOKEN_HANDOFF_WINDOW`` — a device token is a
    # bearer string with a sliding window, and what it says about an
    # authenticator being present is only true near the moment it was minted.
    amr_claimed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
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
