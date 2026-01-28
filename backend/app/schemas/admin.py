"""Admin-related schemas for platform administration."""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.guild import GuildRole
from app.models.initiative import InitiativeRole
from app.models.user import UserRole
from app.schemas.user import ProjectBasic, UserPublic


class PlatformRoleUpdate(BaseModel):
    """Schema for updating a user's platform role."""
    role: UserRole


class PlatformAdminCountResponse(BaseModel):
    """Response schema for platform admin count."""
    count: int


class AdminUserDeleteRequest(BaseModel):
    """Request to delete a user as platform admin."""
    deletion_type: Literal["soft", "hard"]
    project_transfers: Optional[Dict[int, int]] = None  # {project_id: new_owner_id}


class GuildBlockerInfo(BaseModel):
    """Info about a guild blocking user deletion."""
    guild_id: int
    guild_name: str
    other_members: List[UserPublic] = Field(default_factory=list)


class InitiativeBlockerInfo(BaseModel):
    """Info about an initiative blocking user deletion."""
    initiative_id: int
    initiative_name: str
    guild_id: int
    other_members: List[UserPublic] = Field(default_factory=list)


class AdminDeletionEligibilityResponse(BaseModel):
    """Enhanced eligibility response with actionable blocker details."""
    can_delete: bool
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    owned_projects: List[ProjectBasic] = Field(default_factory=list)
    guild_blockers: List[GuildBlockerInfo] = Field(default_factory=list)
    initiative_blockers: List[InitiativeBlockerInfo] = Field(default_factory=list)


class AdminGuildRoleUpdate(BaseModel):
    """Schema for updating a user's guild role via admin endpoint."""
    role: GuildRole


class AdminInitiativeRoleUpdate(BaseModel):
    """Schema for updating a user's initiative role via admin endpoint."""
    role: InitiativeRole
