from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

from app.models._mixins import SoftDeleteMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.initiative import Initiative
    from app.models.project import Project
    from app.models.tag import DocumentTag
    from app.models.queue import QueueItemDocument
    from app.models.calendar_event import CalendarEventDocument
    from app.models.property import DocumentPropertyValue
    from app.models.resource_grant import ResourceGrant


class DocumentType(str, Enum):
    """Discriminator for document type."""

    native = "native"  # Lexical editor document
    file = "file"  # Uploaded file (PDF, DOCX, etc.)
    whiteboard = "whiteboard"  # Excalidraw scene stored in content JSONB
    smart_link = "smart_link"  # URL-backed iframe embed (Figma, YouTube, …)
    spreadsheet = "spreadsheet"  # Sparse cell map; collaborative via yjs


class Document(SoftDeleteMixin, table=True):
    __tablename__ = "documents"
    _owner_field = "created_by_id"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[int] = Field(
        default=None, foreign_key="guilds.id", nullable=True
    )
    initiative_id: int = Field(foreign_key="initiatives.id", nullable=False)
    title: str = Field(nullable=False, index=True, max_length=255)
    content: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
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
    is_template: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    yjs_state: Optional[bytes] = Field(
        default=None,
        sa_column=Column(LargeBinary, nullable=True),
    )
    yjs_updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # File document fields
    document_type: DocumentType = Field(
        default=DocumentType.native,
        sa_column=Column(
            SQLEnum(
                DocumentType,
                name="document_type",
                create_type=False,
            ),
            nullable=False,
            server_default=text("'native'"),
        ),
    )
    file_url: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=512), nullable=True),
    )
    file_content_type: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=128), nullable=True),
    )
    file_size: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    original_filename: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=255), nullable=True),
    )

    initiative: Optional["Initiative"] = Relationship(back_populates="documents")
    project_links: List["ProjectDocument"] = Relationship(
        back_populates="document",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    tag_links: List["DocumentTag"] = Relationship(
        back_populates="document",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    property_values: List["DocumentPropertyValue"] = Relationship(
        back_populates="document",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    grants: List["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == Document.id, "
                "ResourceGrant.resource_type == 'document')"
            ),
            "viewonly": True,
        }
    )
    queue_item_links: List["QueueItemDocument"] = Relationship(
        back_populates="document",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    calendar_event_links: List["CalendarEventDocument"] = Relationship(
        back_populates="document",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    file_versions: List["DocumentFileVersion"] = Relationship(
        back_populates="document",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "DocumentFileVersion.version_number",
        },
    )


class DocumentFileVersion(SQLModel, table=True):
    """A single uploaded version of a file-type document.

    Every file document has at least one row here; the ``documents`` row
    mirrors the file fields of the current version (the highest
    ``version_number``) so the existing download endpoint and viewer keep
    working without consulting this table.
    """

    __tablename__ = "document_file_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "version_number", name="uq_dfv_document_version"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    guild_id: Optional[int] = Field(
        default=None, foreign_key="guilds.id", nullable=True
    )
    version_number: int = Field(nullable=False)
    file_url: str = Field(sa_column=Column(String(length=512), nullable=False))
    file_content_type: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=128), nullable=True),
    )
    file_size: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    original_filename: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=255), nullable=True),
    )
    uploaded_by_id: int = Field(foreign_key="users.id", nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    document: Optional["Document"] = Relationship(back_populates="file_versions")


class ProjectDocument(SQLModel, table=True):
    __tablename__ = "project_documents"

    project_id: int = Field(foreign_key="projects.id", primary_key=True)
    document_id: int = Field(foreign_key="documents.id", primary_key=True)
    guild_id: Optional[int] = Field(
        default=None, foreign_key="guilds.id", nullable=True
    )
    attached_by_id: Optional[int] = Field(
        default=None, foreign_key="users.id", nullable=True
    )
    attached_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    project: Optional["Project"] = Relationship(back_populates="document_links")
    document: Optional[Document] = Relationship(back_populates="project_links")


class DocumentPermissionLevel(str, Enum):
    owner = "owner"
    write = "write"
    read = "read"


class DocumentLink(SQLModel, table=True):
    """Tracks wikilinks between documents for backlinks queries."""

    __tablename__ = "document_links"

    source_document_id: int = Field(foreign_key="documents.id", primary_key=True)
    target_document_id: int = Field(foreign_key="documents.id", primary_key=True)
    guild_id: Optional[int] = Field(
        default=None, foreign_key="guilds.id", nullable=True
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
