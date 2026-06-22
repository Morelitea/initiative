from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlmodel import Field, SQLModel


class AccessLevel(str, Enum):
    """How much access a PAM grant confers within its target guild."""

    read = "read"
    read_write = "read_write"


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
ACCESS_GRANT_STATUSES: tuple[str, ...] = tuple(
    status.value for status in AccessGrantStatus
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

    id: Optional[int] = Field(default=None, primary_key=True)

    # The grantee and the guild they're being granted access to.
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)

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

    # Justification supplied by the requester and the originally-requested
    # window. The effective window is ``decided_at``..``expires_at``, set at
    # approval (capped server-side).
    reason: str = Field(sa_column=Column(Text, nullable=False))
    requested_duration_minutes: int = Field(sa_column=Column(Integer, nullable=False))

    # Actors. ``requested_by_id`` equals ``user_id`` for self-service requests
    # but is kept distinct so an approver could later request on someone's
    # behalf without schema changes.
    requested_by_id: int = Field(foreign_key="users.id", nullable=False)
    approved_by_id: Optional[int] = Field(
        default=None, foreign_key="users.id", nullable=True
    )
    revoked_by_id: Optional[int] = Field(
        default=None, foreign_key="users.id", nullable=True
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
