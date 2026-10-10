"""The demo deployment's copies, the accounts that hold them, and the
addresses visitors leave. A link handing a pitch out is an ordinary invite into
the pitch.

Only a deployment started with ``DEMO_MODE`` writes these; everywhere else
they stay empty. All three are the system engine's alone: a request-path role
reaches none of them.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    UniqueConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlmodel import Field, SQLModel

from app.core.encryption import EMAIL_HASH_COLUMN, FERNET_SALT, SALT_EMAIL


class LinkState(str, Enum):
    """Whether a link still opens copies, and if not, why."""

    live = "live"
    #: Past its end, or ended early.
    expired = "expired"
    used_up = "used_up"


class DemoSandboxState(str, Enum):
    #: Built and waiting for a visitor.
    pooled = "pooled"
    #: Claimed by a link; deleted when it expires.
    live = "live"


class DemoSandbox(SQLModel, table=True):
    """A community built for the pool, and once claimed, a visitor's copy."""

    __tablename__ = "demo_sandboxes"
    __table_args__ = (
        CheckConstraint("state IN ('pooled', 'live')", name="ck_demo_sandboxes_state"),
    )

    guild_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
        )
    )
    state: DemoSandboxState = Field(
        default=DemoSandboxState.pooled,
        sa_column=Column(String, nullable=False, index=True, server_default="pooled"),
    )
    #: The invite into the pitch that opened the copy.
    invite_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("guild_invites.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    claimed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: The import filling the copy, in the copy's own schema.
    import_job_id: Optional[int] = Field(default=None)


class DemoAccount(SQLModel, table=True):
    """An account made for a visitor, tied to the copy it was made for."""

    __tablename__ = "demo_accounts"

    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        )
    )
    sandbox_guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("demo_sandboxes.guild_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )


class DemoLead(SQLModel, table=True):
    """An address a visitor left on the link, an invite into a pitch, that
    opened their copy; kept for 30 days. Apart from any account: a demo account
    has no address."""

    __tablename__ = "demo_leads"
    __table_args__ = (
        UniqueConstraint("invite_id", "email_hash", name="uq_demo_leads_invite_email"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    invite_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guild_invites.id", ondelete="CASCADE"), nullable=False
        )
    )
    #: Keyed hash of the normalised address (``encryption.hash_email``).
    email_hash: str = Field(sa_column=Column(String(64), nullable=False))
    email_encrypted: str = Field(
        sa_column=Column(
            String(2000),
            nullable=False,
            info={FERNET_SALT: SALT_EMAIL, EMAIL_HASH_COLUMN: "email_hash"},
        )
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
