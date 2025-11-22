from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING
import json

from sqlalchemy import Column, DateTime, JSON
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

class ProjectRole(str, Enum):
    admin = "admin"
    project_manager = "project_manager"
    member = "member"


if TYPE_CHECKING:  # pragma: no cover - imported lazily for type checking only
    from app.models.project_order import ProjectOrder
    from app.models.task import Task
    from app.models.user import User
    from app.models.team import Team


DEFAULT_PROJECT_READ_ROLES = [role.value for role in ProjectRole]
DEFAULT_PROJECT_WRITE_ROLES = [ProjectRole.admin.value, ProjectRole.project_manager.value]


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, nullable=False)
    icon: Optional[str] = Field(default=None, max_length=8)
    description: Optional[str] = Field(default=None)
    owner_id: int = Field(foreign_key="users.id", nullable=False)
    team_id: Optional[int] = Field(default=None, foreign_key="teams.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    read_roles: List[str] = Field(
        default_factory=lambda: list(DEFAULT_PROJECT_READ_ROLES),
        sa_column=Column(JSON, nullable=False, server_default=json.dumps(DEFAULT_PROJECT_READ_ROLES)),
    )
    write_roles: List[str] = Field(
        default_factory=lambda: list(DEFAULT_PROJECT_WRITE_ROLES),
        sa_column=Column(JSON, nullable=False, server_default=json.dumps(DEFAULT_PROJECT_WRITE_ROLES)),
    )
    is_archived: bool = Field(default=False, nullable=False)
    is_template: bool = Field(default=False, nullable=False)
    archived_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    owner: Optional["User"] = Relationship(back_populates="projects_owned")
    team: Optional["Team"] = Relationship(back_populates="projects")
    tasks: List["Task"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    members: List["ProjectMember"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    orders: List["ProjectOrder"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class ProjectMember(SQLModel, table=True):
    __tablename__ = "project_members"

    project_id: int = Field(foreign_key="projects.id", primary_key=True)
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    role: ProjectRole = Field(
        default=ProjectRole.member,
        sa_column=Column(SQLEnum(ProjectRole, name="project_role"), nullable=False),
    )
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    project: Optional[Project] = Relationship(back_populates="members")
    user: Optional["User"] = Relationship(back_populates="memberships")
