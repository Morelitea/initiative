from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Enum as SQLEnum, Field, SQLModel

from app.core.encryption import FERNET_PATHS, FERNET_SALT, SALT_EMAIL


class UserTokenPurpose(str, Enum):
    email_verification = "email_verification"
    password_reset = "password_reset"
    #: The link in an account letter that answers "this wasn't me".
    account_change = "account_change"


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
    # What an account_change token may do, and the address it was sent to.
    # NULL for every other token. The address a removal took (``undo.email``)
    # and the one the link went to (``recipient``) are sealed under SALT_EMAIL.
    change: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(
            JSONB,
            nullable=True,
            info={
                FERNET_SALT: SALT_EMAIL,
                FERNET_PATHS: (("undo", "email"), ("recipient",)),
            },
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
