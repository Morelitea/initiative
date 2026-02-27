from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, Relationship, SQLModel
from pydantic import ConfigDict

if TYPE_CHECKING:  # pragma: no cover
    from app.models.guild import Guild
    from app.models.task import Task
    from app.models.project import Project
    from app.models.document import Document
    from app.models.queue import QueueItemTag


class Tag(SQLModel, table=True):
    """Guild-scoped tag for categorizing tasks, projects, and documents.

    Supports nested tag naming via "/" convention (e.g., "books/fiction").
    The "/" is purely visual/organizational - no parent-child DB relationships.
    """
    __tablename__ = "tags"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    name: str = Field(
        sa_column=Column(String(length=100), nullable=False),
    )
    color: str = Field(
        default="#6366F1",
        sa_column=Column(String(length=7), nullable=False, server_default="'#6366F1'"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    guild: Optional["Guild"] = Relationship()
    task_links: List["TaskTag"] = Relationship(
        back_populates="tag",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    project_links: List["ProjectTag"] = Relationship(
        back_populates="tag",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    document_links: List["DocumentTag"] = Relationship(
        back_populates="tag",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    queue_item_links: List["QueueItemTag"] = Relationship(
        back_populates="tag",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class TaskTag(SQLModel, table=True):
    """Junction table linking tasks to tags."""
    __tablename__ = "task_tags"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_id: int = Field(foreign_key="tasks.id", primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", primary_key=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    task: Optional["Task"] = Relationship(back_populates="tag_links")
    tag: Optional[Tag] = Relationship(back_populates="task_links")


class ProjectTag(SQLModel, table=True):
    """Junction table linking projects to tags."""
    __tablename__ = "project_tags"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    project_id: int = Field(foreign_key="projects.id", primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", primary_key=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    project: Optional["Project"] = Relationship(back_populates="tag_links")
    tag: Optional[Tag] = Relationship(back_populates="project_links")


class DocumentTag(SQLModel, table=True):
    """Junction table linking documents to tags."""
    __tablename__ = "document_tags"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    document_id: int = Field(foreign_key="documents.id", primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", primary_key=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    document: Optional["Document"] = Relationship(back_populates="tag_links")
    tag: Optional[Tag] = Relationship(back_populates="document_links")
