"""Admin-related schemas for platform administration."""

from typing import Dict, List, Literal, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel

from app.models.guild import GuildRole
from app.models.initiative import InitiativeRole
from app.models.user import UserRole
from app.schemas.user import ProjectBasic, UserPublic


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
    warnings: List[str] = Field(default_factory=list)
    owned_projects: List[ProjectBasic] = Field(default_factory=list)
    guild_blockers: List[GuildBlockerInfo] = Field(default_factory=list)
    initiative_blockers: List[InitiativeBlockerInfo] = Field(default_factory=list)


class AdminGuildRoleUpdate(SanitizedBaseModel):
    """Schema for updating a user's guild role via admin endpoint."""

    role: GuildRole


class AdminInitiativeRoleUpdate(SanitizedBaseModel):
    """Schema for updating a user's initiative role via admin endpoint."""

    role: InitiativeRole
