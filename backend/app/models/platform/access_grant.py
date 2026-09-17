from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlmodel import Field, Index, SQLModel


class AccessLevel(str, Enum):
    """How much of a guild's *content* a PAM grant confers."""

    read = "read"
    read_write = "read_write"


class SettingsLevel(str, Enum):
    """Which rung of a guild's *configuration* a settings grant confers.

    The guild's own ladder, borrowed: ``admin`` reaches what a guild admin
    administers, ``superadmin`` reaches what the seat holds — its sign-in and
    its billing. There is no default; a request names one.

    Stored in the same ``access_level`` column as :class:`AccessLevel`, which
    the purpose tells apart. A CHECK holds each vocabulary to its own purpose,
    so a settings grant can never read as ``read_write`` content, nor a content
    grant as ``superadmin``.
    """

    admin = "admin"
    superadmin = "superadmin"


class AccessGrantPurpose(str, Enum):
    """What a grant authorises. A grant is only ever spent on its own purpose.

    ``billing`` covers the external billing account and carries no access to
    the guild itself.
    """

    content = "content"
    billing = "billing"
    #: The community's configuration, and nothing inside it. Held at a rung
    #: from :class:`SettingsLevel`. Separate from content on purpose: helping
    #: with billing or moderation settings is not a reason to read somebody's
    #: documents.
    settings = "settings"


class AccessGrantStatus(str, Enum):
    """Lifecycle of a privileged-access grant.

    ``pending`` → (``approved`` | ``denied``); ``approved`` → (``revoked`` |
    ``expired``). A grant is *live* only while ``approved`` and before
    ``expires_at`` — liveness is computed, not stored (see the service).
    """

    pending = "pending"
    approved = "approved"
    denied = "denied"
    revoked = "revoked"
    expired = "expired"


# Mirror the CHECK constraints declared in the migration. Keep in sync with
# ``20260530_0092_create_access_grants.py``.
ACCESS_LEVELS: tuple[str, ...] = tuple(level.value for level in AccessLevel)
SETTINGS_LEVELS: tuple[str, ...] = tuple(level.value for level in SettingsLevel)

#: The translation key naming each level, in the ``accessGrant`` block of both
#: the notifications and email catalogues. One entry per value the column can
#: carry: two vocabularies share it, so anything that fell back to a default
#: would describe a settings grant as a content one to the person being asked
#: to approve it.
LEVEL_LABEL_KEYS: dict[str, str] = {
    "read": "accessGrant.levelRead",
    "read_write": "accessGrant.levelReadWrite",
    "admin": "accessGrant.levelAdmin",
    "superadmin": "accessGrant.levelSuperadmin",
}

#: What ``access_level`` may say, per purpose. The CHECK in migration 0298
#: mirrors this.
LEVELS_BY_PURPOSE: dict[str, tuple[str, ...]] = {
    "content": ACCESS_LEVELS,
    "billing": ACCESS_LEVELS,
    "settings": SETTINGS_LEVELS,
}
ACCESS_GRANT_STATUSES: tuple[str, ...] = tuple(
    status.value for status in AccessGrantStatus
)
ACCESS_GRANT_PURPOSES: tuple[str, ...] = tuple(
    purpose.value for purpose in AccessGrantPurpose
)


class AccessGrant(SQLModel, table=True):
    """A time-bound, per-guild privileged-access grant (PAM).

    A lower-privilege platform user (e.g. ``support``) requests temporary
    access to one guild; an ``owner``/``admin`` approves it; it auto-expires.
    This is the least-privilege alternative to the standing all-guild
    ``data.bypass`` that ``admin``/``owner`` hold.

    Managed cross-guild by platform staff, so endpoints use the admin
    (RLS-bypassing) session with explicit capability + ownership checks —
    the same pattern as the ``users`` table.
    """

    __tablename__ = "access_grants"
    __table_args__ = (
        # The live-grant lookup: "does this user hold a grant on this guild".
        Index("ix_access_grants_user_guild", "user_id", "guild_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # The grantee and the guild they're being granted access to. A grant is
    # meaningless once either side is gone, so both cascade.
    user_id: int = Field(
        foreign_key="users.id", ondelete="CASCADE", nullable=False, index=True
    )
    guild_id: int = Field(
        foreign_key="guilds.id", ondelete="CASCADE", nullable=False, index=True
    )

    access_level: str = Field(
        sa_column=Column(
            String(16), nullable=False, server_default=AccessLevel.read.value
        )
    )
    status: str = Field(
        sa_column=Column(
            String(16),
            nullable=False,
            server_default=AccessGrantStatus.pending.value,
            index=True,
        )
    )
    purpose: str = Field(
        default=AccessGrantPurpose.content.value,
        sa_column=Column(
            String(16),
            nullable=False,
            server_default=AccessGrantPurpose.content.value,
            index=True,
        ),
    )

    # Justification supplied by the requester and the originally-requested
    # window. The effective window is ``decided_at``..``expires_at``, set at
    # approval (capped server-side).
    reason: str = Field(sa_column=Column(Text, nullable=False))
    requested_duration_minutes: int = Field(sa_column=Column(Integer, nullable=False))

    # Actors. ``requested_by_id`` equals ``user_id`` for self-service requests
    # but is kept distinct so an approver could later request on someone's
    # behalf without schema changes.
    # The requester goes with the grant; a decider does not — the audit row
    # outlives the staff account that decided it, so those null out.
    requested_by_id: int = Field(
        foreign_key="users.id", ondelete="CASCADE", nullable=False
    )
    approved_by_id: Optional[int] = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL", nullable=True
    )
    revoked_by_id: Optional[int] = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL", nullable=True
    )

    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    decided_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    revoked_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    def is_live(self, *, now: datetime) -> bool:
        """True iff this grant currently confers access (approved, unexpired)."""
        return (
            self.status == AccessGrantStatus.approved.value
            and self.expires_at is not None
            and self.expires_at > now
        )
