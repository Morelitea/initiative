from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Column, DateTime
from sqlmodel import Field, Relationship

from app.models._mixins import SoftDeleteMixin


if TYPE_CHECKING:  # pragma: no cover - imported lazily for type checking only
    from app.models.project_order import ProjectOrder
    from app.models.task import Task, TaskStatus
    from app.models.user import User
    from app.models.initiative import Initiative
    from app.models.project_activity import ProjectFavorite
    from app.models.document import ProjectDocument
    from app.models.guild import Guild
    from app.models.tag import ProjectTag
    from app.models.resource_grant import ResourceGrant


class Project(SoftDeleteMixin, table=True):
    __tablename__ = "projects"
    _owner_field = "owner_id"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[int] = Field(
        default=None, foreign_key="guilds.id", nullable=True
    )
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
    orders: List["ProjectOrder"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    favorite_entries: List["ProjectFavorite"] = Relationship(
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
    grants: List["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == Project.id, "
                "ResourceGrant.resource_type == 'project')"
            ),
            "viewonly": True,
        }
    )


class ProjectPermissionLevel(str, Enum):
    owner = "owner"
    write = "write"
    read = "read"
