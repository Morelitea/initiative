from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Column, DateTime, Text, Boolean, String, Integer
from sqlmodel import Enum as SQLEnum, Field, SQLModel, Relationship
from pydantic import ConfigDict

from app.models.initiative import InitiativeMember
from app.models.task import TaskAssignee

if TYPE_CHECKING:  # pragma: no cover
    from app.models.guild import GuildMembership


class UserRole(str, Enum):
    admin = "admin"
    member = "member"


class User(SQLModel, table=True):
    __tablename__ = "users"
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    __allow_unmapped__ = True

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True, nullable=False)
    full_name: Optional[str] = Field(default=None)
    hashed_password: str
    role: UserRole = Field(
        sa_column=Column(SQLEnum(UserRole, name="user_role"), nullable=False, server_default=UserRole.member.value)
    )
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    avatar_base64: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    avatar_url: Optional[str] = Field(default=None, nullable=True)
    week_starts_on: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    email_verified: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    timezone: str = Field(
        default="UTC",
        sa_column=Column(String(64), nullable=False, server_default="UTC"),
    )
    overdue_notification_time: str = Field(
        default="21:00",
        sa_column=Column(String(5), nullable=False, server_default="21:00"),
    )
    notify_initiative_addition: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    notify_task_assignment: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    notify_project_added: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    notify_overdue_tasks: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    notify_mentions: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    last_overdue_notification_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_task_assignment_digest_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    active_guild_id: Optional[int] = Field(
        default=None,
        foreign_key="guilds.id",
        nullable=True,
    )

    # AI Settings (nullable = inherit from guild/platform)
    ai_enabled: Optional[bool] = Field(
        default=None,
        sa_column=Column(Boolean, nullable=True),
    )
    ai_provider: Optional[str] = Field(default=None, sa_column=Column(String(50), nullable=True))
    ai_api_key: Optional[str] = Field(default=None, sa_column=Column(String(2000), nullable=True))
    ai_base_url: Optional[str] = Field(default=None, sa_column=Column(String(1000), nullable=True))
    ai_model: Optional[str] = Field(default=None, sa_column=Column(String(500), nullable=True))

    projects_owned: List["Project"] = Relationship(back_populates="owner")
    tasks_assigned: List["Task"] = Relationship(back_populates="assignees", link_model=TaskAssignee)
    project_permissions: List["ProjectPermission"] = Relationship(back_populates="user")
    initiative_memberships: List["InitiativeMember"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    guild_memberships: List["GuildMembership"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    project_orders: List["ProjectOrder"] = Relationship(back_populates="user")
    api_keys: List["UserApiKey"] = Relationship(back_populates="user")
    favorite_projects: List["ProjectFavorite"] = Relationship(back_populates="user")
    recent_project_views: List["RecentProjectView"] = Relationship(back_populates="user")


from app.models.project import Project  # noqa: E402  # isort:skip
from app.models.project import ProjectPermission  # noqa: E402  # isort:skip
from app.models.task import Task  # noqa: E402  # isort:skip
from app.models.project_order import ProjectOrder  # noqa: E402  # isort:skip
from app.models.api_key import UserApiKey  # noqa: E402  # isort:skip
from app.models.project_activity import ProjectFavorite, RecentProjectView  # noqa: E402  # isort:skip
