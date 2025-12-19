from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, computed_field

from app.models.initiative import InitiativeRole
from app.models.user import UserRole
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
    is_active: Optional[bool] = None
    avatar_base64: Optional[str] = None
    avatar_url: Optional[str] = None
    week_starts_on: Optional[int] = None
    timezone: Optional[str] = None
    overdue_notification_time: Optional[str] = None
    notify_initiative_addition: Optional[bool] = None
    notify_task_assignment: Optional[bool] = None
    notify_project_added: Optional[bool] = None
    notify_overdue_tasks: Optional[bool] = None


class UserPublic(BaseModel):
    """Public user information exposed to other users"""
    id: int
    email: EmailStr
    full_name: Optional[str] = None
    avatar_base64: Optional[str] = None
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True


class UserGuildMember(UserPublic):
    """User information for guild member management (includes role/status but not personal settings)"""
    role: UserRole
    is_active: bool
    email_verified: bool
    created_at: datetime
    initiative_roles: List["UserInitiativeRole"] = Field(default_factory=list)

    class Config:
        from_attributes = True


class UserRead(UserBase):
    id: int
    active_guild_id: Optional[int] = None
    is_active: bool
    email_verified: bool
    created_at: datetime
    updated_at: datetime
    avatar_base64: Optional[str] = None
    avatar_url: Optional[str] = None
    week_starts_on: int = 0
    timezone: str = "UTC"
    overdue_notification_time: str = "21:00"
    notify_initiative_addition: bool = True
    notify_task_assignment: bool = True
    notify_project_added: bool = True
    notify_overdue_tasks: bool = True
    last_overdue_notification_at: Optional[datetime] = None
    last_task_assignment_digest_at: Optional[datetime] = None
    initiative_roles: List["UserInitiativeRole"] = Field(default_factory=list)

    @computed_field(return_type=bool)  # type: ignore[misc]
    @property
    def can_create_guilds(self) -> bool:
        return not settings.DISABLE_GUILD_CREATION

    class Config:
        from_attributes = True


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
    notify_initiative_addition: Optional[bool] = None
    notify_task_assignment: Optional[bool] = None
    notify_project_added: Optional[bool] = None
    notify_overdue_tasks: Optional[bool] = None


class ProjectBasic(BaseModel):
    """Basic project information for deletion flow"""
    id: int
    name: str
    initiative_id: int

    class Config:
        from_attributes = True


class AccountDeletionRequest(BaseModel):
    """Request to delete or deactivate a user account"""
    deletion_type: Literal["soft", "hard"]
    password: str
    confirmation_text: str
    project_transfers: Optional[Dict[int, int]] = None  # {project_id: new_owner_id}


class DeletionEligibilityResponse(BaseModel):
    """Response indicating whether user can be deleted and any blockers"""
    can_delete: bool
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    owned_projects: List[ProjectBasic] = Field(default_factory=list)
    last_admin_guilds: List[str] = Field(default_factory=list)


class AccountDeletionResponse(BaseModel):
    """Response after account deletion attempt"""
    success: bool
    deletion_type: str
    message: str
