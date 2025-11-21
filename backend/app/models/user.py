from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from sqlalchemy import Column, DateTime, Text
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

from app.models.team import Team, TeamMember
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

    projects_owned: List["Project"] = Relationship(back_populates="owner")
    tasks_assigned: List["Task"] = Relationship(back_populates="assignees", link_model=TaskAssignee)
    memberships: List["ProjectMember"] = Relationship(back_populates="user")
    teams: List["Team"] = Relationship(back_populates="members", link_model=TeamMember)


from app.models.project import Project  # noqa: E402  # isort:skip
from app.models.project import ProjectMember  # noqa: E402  # isort:skip
from app.models.task import Task  # noqa: E402  # isort:skip
