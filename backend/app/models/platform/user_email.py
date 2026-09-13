"""An address an account can be reached at and sign in with.

One account, many addresses — the shape GitHub uses. ``users.email_hash`` /
``email_encrypted`` hold the one address an account was created with; this
table holds every address it has, with the same two representations: a keyed
HMAC for equality lookups and a Fernet ciphertext for reading it back.

**app_admin-only.** Resolving an address to an account is a pre-auth lookup —
the user is unknown until it returns — so it structurally cannot run under
own-row RLS, exactly like ``auth_sessions``. The schema-default request-path
DML is REVOKEd in the migration.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, Index, SQLModel


class EmailSource(str):
    """Where an address came from. Not an enum column — the value is a note for
    whoever reads the row, and a new way to acquire an address should not need
    a migration."""

    signup = "signup"
    added = "added"
    oidc = "oidc"
    synthetic = "synthetic"


class UserEmail(SQLModel, table=True):
    """One address belonging to one account."""

    __tablename__ = "user_emails"
    __table_args__ = (
        # An address belongs to one account, platform-wide: the same uniqueness
        # users.email_hash carries today.
        UniqueConstraint("email_hash", name="uq_user_emails_email_hash"),
        Index("ix_user_emails_user_id", "user_id"),
        # One primary per account, as a partial unique index rather than a
        # pointer on ``users`` — no nullable column and no circular foreign key.
        Index(
            "uq_user_emails_one_primary",
            "user_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    # Keyed HMAC of the normalised address (app.core.encryption.hash_email) —
    # what an equality lookup and the unique constraint run on.
    email_hash: str = Field(sa_column=Column(String(64), nullable=False))
    # Fernet ciphertext under SALT_EMAIL. Rotated with the users copy, in the
    # same statement, so the hash and the ciphertext never disagree.
    email_encrypted: str = Field(sa_column=Column(String(2000), nullable=False))

    # When the holder proved they hold it. NULL means unproven.
    verified_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # The address that receives account mail. Exactly one per account.
    #
    # Not constrained to a verified address: accounts predating this table may
    # never have verified the one they signed up with, and they still receive
    # mail there. "You cannot move your primary to an address you have not
    # proved you hold" is a rule about the change, and it lives in the code
    # that makes the change.
    is_primary: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=text("false"))
    )
    # signup | added | oidc | synthetic — see EmailSource.
    source: str = Field(sa_column=Column(Text, nullable=False))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # Last time a sign-in resolved through this address, for the account page
    # and for telling a stale address from one in use.
    last_login_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
