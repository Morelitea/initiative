from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel


if TYPE_CHECKING:  # pragma: no cover - imported lazily for type checking only
    from app.models.project_order import ProjectOrder
    from app.models.task import Task, TaskStatus
    from app.models.user import User
    from app.models.initiative import Initiative, InitiativeRoleModel
    from app.models.project_activity import ProjectFavorite, RecentProjectView
    from app.models.document import ProjectDocument
    from app.models.guild import Guild
    from app.models.tag import ProjectTag


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[int] = Field(default=None, foreign_key="guilds.id", nullable=True)
    name: str = Field(index=True, nullable=False)
    icon: Optional[str] = Field(default=None, max_length=8)
    description: Optional[str] = Field(default=None)
    owner_id: int = Field(foreign_key="users.id", nullable=False)
    initiative_id: int = Field(foreign_key="initiatives.id", nullable=False, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    is_archived: bool = Field(default=False, nullable=False)
    is_template: bool = Field(default=False, nullable=False)
    archived_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    pinned_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    owner: Optional["User"] = Relationship(back_populates="projects_owned")
    initiative: Optional["Initiative"] = Relationship(back_populates="projects")
    guild: Optional["Guild"] = Relationship()
    tasks: List["Task"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    task_statuses: List["TaskStatus"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    permissions: List["ProjectPermission"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    orders: List["ProjectOrder"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    favorite_entries: List["ProjectFavorite"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    recent_view_entries: List["RecentProjectView"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    document_links: List["ProjectDocument"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    tag_links: List["ProjectTag"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    role_permissions: List["ProjectRolePermission"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class ProjectPermissionLevel(str, Enum):
    owner = "owner"
    write = "write"
    read = "read"


class ProjectPermission(SQLModel, table=True):
    __tablename__ = "project_permissions"

    project_id: int = Field(foreign_key="projects.id", primary_key=True)
    user_id: int = Field(foreign_key="users.id", primary_key=True, index=True)
    guild_id: Optional[int] = Field(default=None, foreign_key="guilds.id", nullable=True)
    level: ProjectPermissionLevel = Field(
        default=ProjectPermissionLevel.write,
        sa_column=Column(
            SQLEnum(ProjectPermissionLevel, name="project_permission_level"),
            nullable=False,
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    project: Optional[Project] = Relationship(back_populates="permissions")
    user: Optional["User"] = Relationship(back_populates="project_permissions")


class ProjectRolePermission(SQLModel, table=True):
    __tablename__ = "project_role_permissions"

    project_id: int = Field(foreign_key="projects.id", primary_key=True)
    initiative_role_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiative_roles.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    guild_id: int = Field(foreign_key="guilds.id", nullable=False)
    level: ProjectPermissionLevel = Field(
        default=ProjectPermissionLevel.read,
        sa_column=Column(
            SQLEnum(ProjectPermissionLevel, name="project_permission_level", create_type=False),
            nullable=False,
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    project: Optional[Project] = Relationship(back_populates="role_permissions")
    role: Optional["InitiativeRoleModel"] = Relationship()
