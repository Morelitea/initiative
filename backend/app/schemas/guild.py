from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import ConfigDict, EmailStr, Field

from app.schemas.base import RawTextStr, RichTextStr, SanitizedBaseModel

from app.models.guild import GuildRole
from app.schemas.user import GuildRemovalProjectInfo


class GuildBase(SanitizedBaseModel):
    name: str
    description: Optional[RichTextStr] = None
    icon_base64: Optional[RawTextStr] = None


class GuildCreate(GuildBase):
    pass


class GuildRead(GuildBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    role: GuildRole
    position: int
    created_at: datetime
    updated_at: datetime
    retention_days: Optional[int] = None
    member_count: int = 0


class GuildInviteCreate(SanitizedBaseModel):
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = Field(default=1, ge=1)
    invitee_email: Optional[EmailStr] = None


class GuildInviteRead(SanitizedBaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

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
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

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
