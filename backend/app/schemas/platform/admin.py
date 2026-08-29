"""Admin-related schemas for platform administration."""

from typing import Dict, List, Literal, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel

from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.schemas.platform.user import UserPublic


class PlatformRoleUpdate(SanitizedBaseModel):
    """Schema for updating a user's platform role."""

    role: UserRole


class PlatformAdminCountResponse(SanitizedBaseModel):
    """Response schema for platform admin count."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    count: int


class AdminUserDeleteRequest(SanitizedBaseModel):
    """Request to deactivate, anonymize (soft delete), or hard delete a user as platform admin."""

    action: Literal["deactivate", "soft_delete", "hard_delete"]
    # Keyed by "guild_id:project_id" (NOT bare project_id) — numeric project ids
    # repeat across per-guild schemas, so a bare id would collide.
    project_transfers: Optional[Dict[str, int]] = None


class GuildBlockerInfo(SanitizedBaseModel):
    """Info about a guild blocking user deletion."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    guild_id: int
    guild_name: str
    other_members: List[UserPublic] = Field(default_factory=list)


class InitiativeBlockerInfo(SanitizedBaseModel):
    """Info about an initiative blocking user deletion."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    initiative_id: int
    initiative_name: str
    guild_id: int
    other_members: List[UserPublic] = Field(default_factory=list)


class AdminDeletionEligibilityResponse(SanitizedBaseModel):
    """Enhanced eligibility response with actionable blocker details."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_delete: bool
    blockers: List[str] = Field(default_factory=list)
    guild_blockers: List[GuildBlockerInfo] = Field(default_factory=list)


class AdminGuildRoleUpdate(SanitizedBaseModel):
    """Schema for updating a user's guild role via admin endpoint."""

    role: GuildRole


class AdminInitiativeRoleUpdate(SanitizedBaseModel):
    """Schema for updating a user's initiative role via admin endpoint.

    ``role`` is the name of a role defined in that initiative — built-in
    (``project_manager``, ``member``) or custom.
    """

    role: str = Field(..., min_length=1, max_length=100)


class AdminUsernameUpdate(SanitizedBaseModel):
    """The name part a moderator sets on someone else's account.

    The number is not here and never will be: it is drawn, not chosen, by
    anyone. It is re-drawn only if the new pair is already held.
    """

    username: str = Field(max_length=64)


class AdminSuspensionUpdate(SanitizedBaseModel):
    """Freeze an account, or let it go.

    ``reason`` is shown to the person it is about, so it is written for them
    rather than as an internal note.
    """

    suspended: bool
    reason: Optional[str] = Field(default=None, max_length=500)
