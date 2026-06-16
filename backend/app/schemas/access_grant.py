from datetime import datetime, timezone
from typing import Optional

from pydantic import ConfigDict, Field, computed_field

from app.models.access_grant import AccessGrantStatus, AccessLevel
from app.schemas.base import SanitizedBaseModel


class AccessGrantCreate(SanitizedBaseModel):
    """A request for time-bound access to one guild."""

    guild_id: int
    access_level: AccessLevel = AccessLevel.read
    # Omit to use the platform default; capped server-side to the configured
    # maximum regardless of what's requested.
    requested_duration_minutes: Optional[int] = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=2000)


class BreakGlassCreate(SanitizedBaseModel):
    """A self-approved, time-bound break-glass grant to one guild.

    Issued by a ``data.bypass`` holder (admin/owner) who needs emergency
    access without waiting for a second-person approval. Read-only by default;
    ``read_write`` is a deliberate escalation. The window is short and capped
    server-side (``PAM_BREAK_GLASS_MAX_MINUTES``) — re-issue to extend.
    """

    guild_id: int
    access_level: AccessLevel = AccessLevel.read
    # Omit to use the break-glass default; capped server-side to the
    # break-glass maximum regardless of what's requested.
    requested_duration_minutes: Optional[int] = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=2000)


class AccessGrantApprove(SanitizedBaseModel):
    """Approval payload. The approver may shorten/extend the window, still
    subject to the server-side cap."""

    duration_minutes: Optional[int] = Field(default=None, gt=0)


class AccessGrantRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    user_id: int
    guild_id: int
    access_level: AccessLevel
    status: AccessGrantStatus
    reason: str
    requested_duration_minutes: int
    requested_by_id: int
    approved_by_id: Optional[int] = None
    revoked_by_id: Optional[int] = None
    requested_at: datetime
    decided_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    # Enrichment populated by the service for display (avoids the client
    # re-fetching users/guilds). Optional so ``model_validate`` over a bare
    # ORM row still works.
    user_email: Optional[str] = None
    user_full_name: Optional[str] = None
    guild_name: Optional[str] = None
    approved_by_email: Optional[str] = None

    @computed_field(return_type=bool)  # type: ignore[misc]
    @property
    def is_live(self) -> bool:
        """Whether this grant currently confers access (approved, unexpired)."""
        return (
            self.status == AccessGrantStatus.approved
            and self.expires_at is not None
            and self.expires_at > datetime.now(timezone.utc)
        )
