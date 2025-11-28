from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Column, DateTime, JSON, String, text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.initiative import Initiative
    from app.models.project import Project


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(foreign_key="initiatives.id", nullable=False)
    title: str = Field(nullable=False, index=True, max_length=255)
    content: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default=text("'{}'::jsonb")),
    )
    created_by_id: int = Field(foreign_key="users.id", nullable=False)
    updated_by_id: int = Field(foreign_key="users.id", nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    featured_image_url: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=512), nullable=True),
    )

    initiative: Optional["Initiative"] = Relationship(back_populates="documents")
    project_links: List["ProjectDocument"] = Relationship(
        back_populates="document",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class ProjectDocument(SQLModel, table=True):
    __tablename__ = "project_documents"

    project_id: int = Field(foreign_key="projects.id", primary_key=True)
    document_id: int = Field(foreign_key="documents.id", primary_key=True)
    attached_by_id: Optional[int] = Field(default=None, foreign_key="users.id", nullable=True)
    attached_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    project: Optional["Project"] = Relationship(back_populates="document_links")
    document: Optional[Document] = Relationship(back_populates="project_links")
