from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import (
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.core.email_masking import mask_email
from app.models.platform.access_grant import (
    AccessGrantStatus,
    AccessLevel,
    SettingsLevel,
)
from app.models.platform.guild import GuildStatus
from app.schemas.base import SanitizedBaseModel


class AccessGrantCreate(SanitizedBaseModel):
    """A request for time-bound access to one guild.

    Two kinds, asked for one at a time. A **content** request reaches what is
    inside the community, at ``read`` or ``read_write``. A **settings** request
    reaches its configuration and nothing inside it, at ``admin`` or
    ``superadmin`` — helping with billing or a moderation setting is not a
    reason to read anybody's documents, so the two are never one ask.

    A settings request names its rung: there is no sensible default between
    "what an admin runs" and "what the seat holds".
    """

    guild_id: int
    purpose: Literal["content", "settings"] = "content"
    #: The content rung, for a content request. Ignored for a settings one.
    access_level: AccessLevel = AccessLevel.read
    #: The settings rung. Required for a settings request, refused otherwise.
    settings_level: Optional[SettingsLevel] = None
    # Omit to use the platform default; capped server-side to the configured
    # maximum regardless of what's requested.
    requested_duration_minutes: Optional[int] = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _rung_matches_purpose(self) -> "AccessGrantCreate":
        if self.purpose == "settings" and self.settings_level is None:
            raise ValueError("settings_level is required for a settings request")
        if self.purpose != "settings" and self.settings_level is not None:
            raise ValueError("settings_level belongs to a settings request")
        return self

    @property
    def level(self) -> str:
        """What goes in ``access_grants.access_level``, per purpose."""
        if self.purpose == "settings":
            assert self.settings_level is not None  # the validator above
            return self.settings_level.value
        return self.access_level.value


class BreakGlassCreate(SanitizedBaseModel):
    """A self-approved, time-bound break-glass grant to one guild.

    Issued by a ``data.bypass`` holder who needs emergency access without
    waiting for a second-person approval. It is not a dial: breaking glass
    issues write access to the community's content **and** a settings grant at
    ``superadmin``, because that is what an emergency is for. Somebody who
    wants less asks for less through the ordinary request flow. The window is
    short and capped server-side (``PAM_BREAK_GLASS_MAX_MINUTES``) — re-issue
    to extend.
    """

    guild_id: int
    # Omit to use the break-glass default; capped server-side to the
    # break-glass maximum regardless of what's requested.
    requested_duration_minutes: Optional[int] = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=2000)
    # The account's own second factor, asked for once any ``data.bypass``
    # holder has one. Either answer is accepted, as everywhere else.
    code: Optional[str] = Field(default=None, max_length=64)
    recovery_code: Optional[str] = Field(default=None, max_length=64)


class AccessGrantApprove(SanitizedBaseModel):
    """Approval payload. The approver may shorten/extend the window, still
    subject to the server-side cap."""

    duration_minutes: Optional[int] = Field(default=None, gt=0)


class AccessGrantRead(SanitizedBaseModel):
    # ``validate_assignment`` is deliberate, not a default: the enrichment
    # fields below are assigned by ``access_grants`` *after* the row has been
    # validated, and field validators run on assignment only when it is set.
    # It is what applies the masking below to those two fields.
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_serialization_defaults_required=True,
        validate_assignment=True,
    )

    id: int
    user_id: int
    guild_id: int
    #: What this grant is for. ``purpose`` is what tells the two vocabularies
    #: below apart: a content grant's level is ``read``/``read_write``, a
    #: settings grant's is ``admin``/``superadmin``.
    purpose: str = "content"
    access_level: str
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
    #: Masked (``u***1@e***m``). An approver reads this row to decide on a
    #: request; the full name and user id beside it identify the requester.
    user_email: Optional[str] = None
    user_full_name: Optional[str] = None
    guild_name: Optional[str] = None
    # The grant's guild lifecycle status, so an operator holding the grant sees
    # a suspended / read-only guild they're acting in (surfaced in the access
    # banner). Operators get this context — unlike a plain guild member.
    guild_status: Optional[GuildStatus] = None
    #: Masked, as ``user_email`` is.
    approved_by_email: Optional[str] = None

    @field_validator("user_email", "approved_by_email", mode="after")
    @classmethod
    def _mask_emails(cls, value: Optional[str]) -> Optional[str]:
        return mask_email(value)

    @computed_field(return_type=bool)  # type: ignore[misc]
    @property
    def is_live(self) -> bool:
        """Whether this grant currently confers access (approved, unexpired)."""
        return (
            self.status == AccessGrantStatus.approved
            and self.expires_at is not None
            and self.expires_at > datetime.now(timezone.utc)
        )


class BreakGlassRequirements(SanitizedBaseModel):
    """What a break-glass request will be asked for, before it is made.

    The form reads this to know whether to offer a code field, and whether the
    caller has a factor to answer with.
    """

    second_factor_required: bool
    enrolled: bool
