"""Schemas for the platform operator surfaces."""

from typing import Dict, List, Literal, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel

from app.models.platform.user import UserRole


class PlatformRoleUpdate(SanitizedBaseModel):
    """Schema for updating a user's platform role."""

    role: UserRole


class OperatorUserDeleteRequest(SanitizedBaseModel):
    """Request to deactivate, anonymize (soft delete), or hard delete another account."""

    action: Literal["deactivate", "soft_delete", "hard_delete"]
    # Keyed by "guild_id:project_id" (NOT bare project_id) — numeric project ids
    # repeat across per-guild schemas, so a bare id would collide.
    project_transfers: Optional[Dict[str, int]] = None


class GuildBlockerInfo(SanitizedBaseModel):
    """Info about a guild blocking user deletion."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    guild_id: int
    guild_name: str


class OperatorDeletionEligibilityResponse(SanitizedBaseModel):
    """Enhanced eligibility response with actionable blocker details."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_delete: bool
    blockers: List[str] = Field(default_factory=list)
    guild_blockers: List[GuildBlockerInfo] = Field(default_factory=list)


class OperatorUsernameUpdate(SanitizedBaseModel):
    """The name part a moderator sets on someone else's account.

    The number is not here and never will be: it is drawn, not chosen, by
    anyone. It is re-drawn only if the new pair is already held.
    """

    username: str = Field(max_length=64)


class OperatorSuspensionUpdate(SanitizedBaseModel):
    """Freeze an account, or let it go.

    ``reason`` is shown to the person it is about, so it is written for them
    rather than as an internal note.
    """

    suspended: bool
    reason: Optional[str] = Field(default=None, max_length=500)
