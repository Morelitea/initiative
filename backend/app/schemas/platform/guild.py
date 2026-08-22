from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import ConfigDict, EmailStr, Field

from app.schemas.base import RawTextStr, RichTextStr, SanitizedBaseModel

from app.models.platform.guild import GuildRole, GuildStatus


class GuildBase(SanitizedBaseModel):
    name: str
    description: Optional[RichTextStr] = None
    icon_base64: Optional[RawTextStr] = None


class GuildCreate(GuildBase):
    #: Make another account the guild's admin instead of the caller.
    #:
    #: Honoured only for a caller holding ``guilds.manage``; anyone else
    #: sending it is refused rather than quietly ignored, so a request that
    #: names an owner never succeeds under a different one. The account must
    #: already exist — this never creates one.
    owner_user_id: Optional[int] = Field(default=None, ge=1)


class GuildRead(GuildBase):
    """A guild as its own members see it (``GET /guilds/`` and friends).

    The payload has two tiers, decided in one place — ``_serialize_guild`` in
    the guilds router:

    - The fields below with no note are for **every member**: guild identity,
      the caller's own membership, the roster size, ``content_read_only``.
    - The ones marked ADMIN-ONLY are guild administration — caps, plan label,
      retention window, lifecycle status, sign-in entitlement. They back
      admin-gated surfaces, so a regular member's payload leaves them ``None``.
      (Operators read the same underlying columns through
      :class:`PlatformGuildStorageRead` instead, which is capability-gated.)
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    role: GuildRole
    position: int
    created_at: datetime
    updated_at: datetime
    # ADMIN-ONLY. Trash retention window, set from the guild's trash settings tab.
    retention_days: Optional[int] = None
    # ADMIN-ONLY. Operator-set caps, rendered against usage on the settings page
    # (the usage half, /g/{id}/storage/usage, is guild-admin only too).
    max_storage_bytes: Optional[int] = None
    max_users: Optional[int] = None
    member_count: int = 0
    # ADMIN-ONLY. Display/audit label of the paid tier (NULL = none /
    # self-hosted). Shown by the plan panel only when a billing portal is
    # configured; it is DISPLAY metadata and is never read in an enforcement
    # path (billing_foss_test scans for that). Enforcement reads
    # max_storage_bytes / max_users / status.
    tier_name: Optional[str] = None
    # ADMIN-ONLY. Lifecycle status, so their settings page can show a "contact
    # your operator" chip. ``None`` for non-admin members — the moderation hold
    # is never disclosed to them (suspended guilds are also filtered from their
    # guild list entirely).
    status: Optional[GuildStatus] = None
    # True when content writes are frozen (read_only lifecycle status). Unlike
    # ``status`` this IS serialized to every member: writes fail at the
    # database role level regardless, so the UI must be able to drop its write
    # affordances — the flag discloses the effect, not the reason.
    content_read_only: bool = False
    # ADMIN-ONLY. Whether this guild may configure its own sign-in (operator
    # entitlement), so their settings UI can show/hide the Authentication tab;
    # ``None`` for non-admin members (they never configure auth). Only
    # meaningful under the per-guild AUTH_SCOPE posture.
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
    created_by: Optional[int]
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
    # Plan label exactly as the billing service last set it — display/audit
    # metadata, never an enforcement input (the caps below are what enforce).
    # Echoed verbatim; this app neither invents nor interprets a plan name, and
    # None means no billing service has named one for this guild.
    tier_name: Optional[str] = None
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

    Being the guild's last admin is the only thing that stops them. Content they
    own is released on the way out and left unowned for a guild admin to claim,
    so there is nothing to hand over first.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_leave: bool
    is_last_admin: bool
