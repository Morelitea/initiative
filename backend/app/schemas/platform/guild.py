from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import ConfigDict, EmailStr, Field

from app.schemas.base import RawTextStr, RichTextStr, SanitizedBaseModel

from app.models.platform.guild import GuildRole, GuildStatus
from app.schemas.platform.user import GuildRemovalProjectInfo


class GuildBase(SanitizedBaseModel):
    name: str
    description: Optional[RichTextStr] = None
    icon_base64: Optional[RawTextStr] = None


class GuildCreate(GuildBase):
    pass


class GuildRead(GuildBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    role: GuildRole
    position: int
    created_at: datetime
    updated_at: datetime
    retention_days: Optional[int] = None
    max_storage_bytes: Optional[int] = None
    max_users: Optional[int] = None
    member_count: int = 0
    # Display/audit label of the paid tier (NULL = none / self-hosted). Shown by
    # the plan panel only when a billing portal is configured; it is DISPLAY
    # metadata and is never read in an enforcement path (billing_foss_test
    # scans for that). Enforcement reads max_storage_bytes / max_users / status.
    tier_name: Optional[str] = None
    # Lifecycle status, surfaced to guild ADMINS only (so their settings page can
    # show a "contact your operator" chip). ``None`` for non-admin members — the
    # moderation hold is never disclosed to them (suspended guilds are also
    # filtered from their guild list entirely).
    status: Optional[GuildStatus] = None
    # True when content writes are frozen (read_only lifecycle status). Unlike
    # ``status`` this IS serialized to every member: writes fail at the
    # database role level regardless, so the UI must be able to drop its write
    # affordances — the flag discloses the effect, not the reason.
    content_read_only: bool = False
    # Whether this guild may configure its own sign-in (operator entitlement).
    # Surfaced to guild ADMINS only, so their settings UI can show/hide the
    # Authentication tab; ``None`` for non-admin members (they never configure
    # auth). Only meaningful under the per-guild AUTH_SCOPE posture.
    guild_auth_enabled: Optional[bool] = None


class GuildInviteCreate(SanitizedBaseModel):
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = Field(default=1, ge=1)
    invitee_email: Optional[EmailStr] = None


class GuildInviteRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    code: str
    guild_id: int
    created_by_user_id: Optional[int]
    expires_at: Optional[datetime]
    max_uses: Optional[int]
    uses: int
    invitee_email: Optional[str]
    created_at: datetime


class GuildInviteAcceptRequest(SanitizedBaseModel):
    code: str


class GuildInviteStatus(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    code: str
    guild_id: Optional[int] = None
    guild_name: Optional[str] = None
    is_valid: bool
    reason: Optional[str] = None
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None
    uses: Optional[int] = None


class GuildUpdate(SanitizedBaseModel):
    name: Optional[str] = None
    description: Optional[RichTextStr] = None
    icon_base64: Optional[RawTextStr] = None
    # Trash retention period in days. None means "never auto-purge".
    # Sentinel "unset" semantics: explicitly omit the field to leave the
    # current setting untouched; set null to switch to never-purge.
    retention_days: Optional[int] = Field(default=None, ge=1, le=3650)
    # NOTE: deliberately no cap/status/tier fields here. Those are
    # operator/billing enforcement inputs (the platform Guilds tab or the
    # verified billing path) — a guild's own admins must never set them, and
    # the column-scoped UPDATE grant on public.guilds (migration 0138) makes
    # the database enforce that even if a field regressed into this schema.


class PlatformGuildStorageRead(SanitizedBaseModel):
    """Operator view of a guild's storage cap (platform settings → Guilds tab).

    Unlike :class:`GuildRead`, this carries no per-user membership fields
    (``role``/``position``): the platform operator lists every guild regardless
    of whether they belong to it, so only platform-wide attributes apply.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    member_count: int = 0
    # Max total stored blob bytes for this guild. None means "unlimited".
    max_storage_bytes: Optional[int] = None
    # Max number of members for this guild. None means "unlimited".
    max_users: Optional[int] = None
    # Operator-set lifecycle status (active / read_only / suspended). Surfaced
    # only to platform operators here — never to guild members (GuildRead omits it).
    status: GuildStatus = GuildStatus.active
    status_changed_at: Optional[datetime] = None
    # Per-guild sign-in entitlement (operator toggle). Only meaningful under the
    # per-guild AUTH_SCOPE posture; the dashboard hides the control otherwise.
    guild_auth_enabled: bool = False


class PlatformGuildStorageUpdate(SanitizedBaseModel):
    """Set a guild's storage caps and/or lifecycle status from the Guilds tab.

    The cap fields use omit-to-skip sentinel semantics (the endpoint inspects
    ``model_fields_set``): omit a field to leave it untouched, send ``null`` to
    reset that cap to unlimited, or send a number to set it. ``status`` is
    omit-to-skip too (a lifecycle status is never null), validated against
    :class:`GuildStatus`. A PATCH may carry any subset.
    """

    max_storage_bytes: Optional[int] = Field(default=None, ge=0)
    max_users: Optional[int] = Field(default=None, ge=1)
    status: Optional[GuildStatus] = None
    # Per-guild sign-in entitlement. Omit-to-skip (a bool is never null here).
    guild_auth_enabled: Optional[bool] = None


class GuildAuthPolicyRead(SanitizedBaseModel):
    """The guild's sign-in requirement. ``open`` is the default (no stored
    row); ``required`` names the provider a session must have satisfied."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    policy: Literal["open", "required"]
    provider_id: Optional[int] = None
    provider_slug: Optional[str] = None
    provider_display_name: Optional[str] = None


class GuildAuthPolicyUpdate(SanitizedBaseModel):
    policy: Literal["open", "required"]
    provider_id: Optional[int] = None


class GuildDeletionRequest(SanitizedBaseModel):
    """Body for ``DELETE /guilds/{id}``.

    Deleting a guild cascades through every initiative, project, task,
    document, membership, invite, and settings row it owns, so the
    endpoint gates on two confirmations:

    - ``confirmation_text`` must equal ``DELETE GUILD <NAME>`` (the whole
      phrase uppercased) so the action can't be triggered by a stray click.
    - ``password`` is the current user's password. It is ignored for
      OIDC-only users (who have no usable password), mirroring the
      account-deletion endpoint, which is why it defaults to empty.
    """

    password: RawTextStr = ""
    confirmation_text: str


class GuildOrderUpdate(SanitizedBaseModel):
    model_config = ConfigDict(populate_by_name=True)
    guild_ids: list[int] = Field(min_length=1, alias="guildIds")


class GuildSummary(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    icon_base64: Optional[RawTextStr] = None


class GuildMembershipUpdate(SanitizedBaseModel):
    """Schema for updating a user's guild membership role."""

    role: GuildRole


class LeaveGuildEligibilityResponse(SanitizedBaseModel):
    """Response for checking if a user can leave a guild.

    ``owned_projects`` lists projects in this guild whose ``owner_id``
    is the current user, with the project-manager candidates the
    leaving user can hand each project to. Leaving without
    re-assigning would orphan the project — the user's
    ``InitiativeMember`` row is dropped on leave, RLS gates the
    project, and there's no DAC bypass for guild admins. The leave
    endpoint requires a transfer-or-delete disposition for each entry
    on this list before it will proceed.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_leave: bool
    is_last_admin: bool
    sole_pm_initiatives: list[str] = []
    owned_projects: list[GuildRemovalProjectInfo] = Field(default_factory=list)


class LeaveGuildRequest(SanitizedBaseModel):
    """Body for ``DELETE /guilds/{id}/leave``.

    Every project the leaving user owns in this guild must appear in
    exactly one of ``project_transfers`` (hand it to another active
    member of the project's initiative) or ``project_deletions`` (send
    it to trash so the guild's retention window can purge it later).
    Empty body is equivalent to ``{}`` — fine when the user owns
    nothing; rejected by the endpoint with
    ``CANNOT_LEAVE_OWNS_PROJECTS`` otherwise.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    project_transfers: dict[int, int] = Field(default_factory=dict)
    project_deletions: list[int] = Field(default_factory=list)
