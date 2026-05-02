from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

from app.models.initiative import InitiativeRole
from app.models.user import UserRole, UserStatus
from app.core.config import settings


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    role: UserRole = UserRole.member


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    password: Optional[str] = None
    status: Optional[UserStatus] = None
    avatar_base64: Optional[str] = None
    avatar_url: Optional[str] = None
    week_starts_on: Optional[int] = None
    timezone: Optional[str] = None
    overdue_notification_time: Optional[str] = None
    email_initiative_addition: Optional[bool] = None
    email_task_assignment: Optional[bool] = None
    email_project_added: Optional[bool] = None
    email_overdue_tasks: Optional[bool] = None
    email_mentions: Optional[bool] = None
    push_initiative_addition: Optional[bool] = None
    push_task_assignment: Optional[bool] = None
    push_project_added: Optional[bool] = None
    push_overdue_tasks: Optional[bool] = None
    push_mentions: Optional[bool] = None
    color_theme: Optional[str] = None
    task_completion_visual_feedback: Optional[str] = None
    task_completion_audio_feedback: Optional[bool] = None
    task_completion_haptic_feedback: Optional[bool] = None
    locale: Optional[str] = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")


class UserPublic(BaseModel):
    """Public user information exposed to other users.

    Includes ``status`` so the frontend can render the "Deleted user #{id}"
    placeholder for anonymized accounts wherever a person appears
    (comment authors, task assignees, mentions, calendar attendees).
    """
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    email: EmailStr
    full_name: Optional[str] = None
    avatar_base64: Optional[str] = None
    avatar_url: Optional[str] = None
    status: UserStatus = UserStatus.active


class UserGuildMember(UserPublic):
    """User information for guild member management (includes role/status but not personal settings)"""

    role: UserRole  # Platform role
    guild_role: Optional[str] = None  # Guild role (admin/member) - set by endpoint
    oidc_managed: bool = False  # Whether membership is managed via OIDC claim mappings
    status: UserStatus
    email_verified: bool
    created_at: datetime
    initiative_roles: List["UserInitiativeRole"] = Field(default_factory=list)


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    status: UserStatus
    email_verified: bool
    created_at: datetime
    updated_at: datetime
    avatar_base64: Optional[str] = None
    avatar_url: Optional[str] = None
    week_starts_on: int = 0
    timezone: str = "UTC"
    overdue_notification_time: str = "21:00"
    email_initiative_addition: bool = True
    email_task_assignment: bool = True
    email_project_added: bool = True
    email_overdue_tasks: bool = True
    email_mentions: bool = True
    push_initiative_addition: bool = True
    push_task_assignment: bool = True
    push_project_added: bool = True
    push_overdue_tasks: bool = True
    push_mentions: bool = True
    last_overdue_notification_at: Optional[datetime] = None
    last_task_assignment_digest_at: Optional[datetime] = None
    color_theme: str = "kobold"
    task_completion_visual_feedback: str = "none"
    task_completion_audio_feedback: bool = True
    task_completion_haptic_feedback: bool = True
    locale: str = "en"
    # Non-null for users provisioned via OIDC SSO; consumed by the
    # self-deletion dialog so it can hide the password gate, since
    # OIDC-only accounts have no usable password to type in.
    oidc_sub: Optional[str] = None
    initiative_roles: List["UserInitiativeRole"] = Field(default_factory=list)

    @computed_field(return_type=bool)  # type: ignore[misc]
    @property
    def can_create_guilds(self) -> bool:
        if not settings.DISABLE_GUILD_CREATION:
            return True
        # When disabled, only platform admins can create guilds
        return self.role == UserRole.admin


class UserInDB(UserRead):
    hashed_password: str


class UserInitiativeRole(BaseModel):
    initiative_id: int
    initiative_name: str
    role: InitiativeRole


class UserSelfUpdate(BaseModel):
    full_name: Optional[str] = None
    password: Optional[str] = None
    avatar_base64: Optional[str] = None
    avatar_url: Optional[str] = None
    week_starts_on: Optional[int] = None
    timezone: Optional[str] = None
    overdue_notification_time: Optional[str] = None
    email_initiative_addition: Optional[bool] = None
    email_task_assignment: Optional[bool] = None
    email_project_added: Optional[bool] = None
    email_overdue_tasks: Optional[bool] = None
    email_mentions: Optional[bool] = None
    push_initiative_addition: Optional[bool] = None
    push_task_assignment: Optional[bool] = None
    push_project_added: Optional[bool] = None
    push_overdue_tasks: Optional[bool] = None
    push_mentions: Optional[bool] = None
    color_theme: Optional[str] = None
    task_completion_visual_feedback: Optional[str] = None
    task_completion_audio_feedback: Optional[bool] = None
    task_completion_haptic_feedback: Optional[bool] = None
    locale: Optional[str] = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")


class ProjectBasic(BaseModel):
    """Basic project information for deletion flow"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    initiative_id: int


class AccountDeletionRequest(BaseModel):
    """Request from a user to deactivate or anonymize (soft-delete) their own account.

    `hard_delete` is intentionally not allowed from this self-service endpoint;
    only platform admins can purge a row, and they do so via the admin endpoint.
    """
    action: Literal["deactivate", "soft_delete"]
    password: str
    confirmation_text: str
    project_transfers: Optional[Dict[int, int]] = None  # {project_id: new_owner_id}


class DeletionEligibilityResponse(BaseModel):
    """Response indicating whether user can be deleted and any blockers"""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_delete: bool
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    owned_projects: List[ProjectBasic] = Field(default_factory=list)
    last_admin_guilds: List[str] = Field(default_factory=list)


class GuildRemovalProjectInfo(BaseModel):
    """Per-project payload on ``GuildRemovalEligibilityResponse``.

    Bundles the candidate transfer recipients next to the project so
    the SPA can render the picker without a second round-trip. The
    leave-guild path uses ``GET /users/me/initiative-members/...``
    instead — but a guild admin removing someone may not themselves
    be a member of every initiative the target user belongs to, so
    that endpoint isn't always callable from this flow.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    initiative_id: int
    candidates: List[UserPublic] = Field(default_factory=list)


class GuildRemovalEligibilityResponse(BaseModel):
    """Pre-flight info for ``DELETE /users/{user_id}`` (guild admin
    removes a member from their guild).

    Mirrors the leave-guild eligibility shape for the same reason: the
    SPA needs to know up-front whether the admin will be prompted to
    pick replacement owners for projects the target user owns. Without
    this, the existing one-click "remove member" path silently
    orphaned every project where the leaving user was sole owner.
    """
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_remove: bool
    sole_pm_initiatives: List[str] = Field(default_factory=list)
    owned_projects: List[GuildRemovalProjectInfo] = Field(default_factory=list)


class GuildRemovalRequest(BaseModel):
    """Body for ``DELETE /users/{user_id}``.

    Every project the target user owns in the active guild must
    appear in exactly one of ``project_transfers`` (hand it to
    another active project manager) or ``project_deletions`` (send
    it to trash so the guild's retention window can purge it). The
    delete branch exists so an admin can still remove a user from a
    guild where no other project manager is available — without it,
    a sole-PM situation would leave the admin with a forever-disabled
    Remove button.
    """
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    project_transfers: Dict[int, int] = Field(default_factory=dict)
    project_deletions: List[int] = Field(default_factory=list)


class AccountDeletionResponse(BaseModel):
    """Response after a deactivate / anonymize / hard-delete action."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    success: bool
    action: str
    message: str
