from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from sqlalchemy import Column, DateTime, Text, Boolean
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

from app.models.initiative import Initiative, InitiativeMember
from app.models.task import TaskAssignee


class UserRole(str, Enum):
    admin = "admin"
    project_manager = "project_manager"
    member = "member"


class User(SQLModel, table=True):
    __tablename__ = "users"

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
    show_project_sidebar: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    show_project_tabs: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    projects_owned: List["Project"] = Relationship(back_populates="owner")
    tasks_assigned: List["Task"] = Relationship(back_populates="assignees", link_model=TaskAssignee)
    memberships: List["ProjectMember"] = Relationship(back_populates="user")
    initiatives: List["Initiative"] = Relationship(back_populates="members", link_model=InitiativeMember)
    project_orders: List["ProjectOrder"] = Relationship(back_populates="user")
    api_keys: List["AdminApiKey"] = Relationship(back_populates="user")
    favorite_projects: List["ProjectFavorite"] = Relationship(back_populates="user")
    recent_project_views: List["RecentProjectView"] = Relationship(back_populates="user")


from app.models.project import Project  # noqa: E402  # isort:skip
from app.models.project import ProjectMember  # noqa: E402  # isort:skip
from app.models.task import Task  # noqa: E402  # isort:skip
from app.models.project_order import ProjectOrder  # noqa: E402  # isort:skip
from app.models.api_key import AdminApiKey  # noqa: E402  # isort:skip
from app.models.project_activity import ProjectFavorite, RecentProjectView  # noqa: E402  # isort:skip
