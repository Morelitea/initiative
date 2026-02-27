from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from pydantic import ConfigDict
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.initiative import Initiative, InitiativeRoleModel
    from app.models.user import User
    from app.models.tag import Tag
    from app.models.document import Document
    from app.models.task import Task


class Queue(SQLModel, table=True):
    """Initiative-scoped queue for turn/priority tracking."""
    __tablename__ = "queues"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    initiative_id: int = Field(foreign_key="initiatives.id", nullable=False, index=True)
    name: str = Field(nullable=False, max_length=255)
    description: Optional[str] = Field(default=None)
    created_by_id: int = Field(foreign_key="users.id", nullable=False)
    current_item_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("queue_items.id", ondelete="SET NULL", use_alter=True),
            nullable=True,
        ),
    )
    current_round: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default="1"),
    )
    is_active: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    initiative: Optional["Initiative"] = Relationship(back_populates="queues")
    items: List["QueueItem"] = Relationship(
        back_populates="queue",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "foreign_keys": "[QueueItem.queue_id]",
        },
    )
    permissions: List["QueuePermission"] = Relationship(
        back_populates="queue",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    role_permissions: List["QueueRolePermission"] = Relationship(
        back_populates="queue",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class QueueItem(SQLModel, table=True):
    """Standalone entry in a queue (character, creature, etc.)."""
    __tablename__ = "queue_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    queue_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("queues.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    label: str = Field(nullable=False, max_length=255)
    position: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", nullable=True)
    color: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=32), nullable=True),
    )
    notes: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    is_visible: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    queue: Optional[Queue] = Relationship(
        back_populates="items",
        sa_relationship_kwargs={"foreign_keys": "[QueueItem.queue_id]"},
    )
    user: Optional["User"] = Relationship()
    tag_links: List["QueueItemTag"] = Relationship(
        back_populates="queue_item",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    document_links: List["QueueItemDocument"] = Relationship(
        back_populates="queue_item",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    task_links: List["QueueItemTask"] = Relationship(
        back_populates="queue_item",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class QueueItemTag(SQLModel, table=True):
    """Junction table linking queue items to tags."""
    __tablename__ = "queue_item_tags"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    queue_item_id: int = Field(foreign_key="queue_items.id", primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", primary_key=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    queue_item: Optional[QueueItem] = Relationship(back_populates="tag_links")
    tag: Optional["Tag"] = Relationship(back_populates="queue_item_links")


class QueuePermissionLevel(str, Enum):
    owner = "owner"
    write = "write"
    read = "read"


class QueuePermission(SQLModel, table=True):
    """Per-user permission on a queue."""
    __tablename__ = "queue_permissions"

    queue_id: int = Field(foreign_key="queues.id", primary_key=True)
    user_id: int = Field(foreign_key="users.id", primary_key=True, index=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False)
    level: QueuePermissionLevel = Field(
        default=QueuePermissionLevel.write,
        sa_column=Column(
            SQLEnum(
                QueuePermissionLevel,
                name="queue_permission_level",
                create_type=False,
            ),
            nullable=False,
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    queue: Optional[Queue] = Relationship(back_populates="permissions")


class QueueRolePermission(SQLModel, table=True):
    """Per-initiative-role permission on a queue."""
    __tablename__ = "queue_role_permissions"

    queue_id: int = Field(foreign_key="queues.id", primary_key=True)
    initiative_role_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiative_roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    guild_id: int = Field(foreign_key="guilds.id", nullable=False)
    level: QueuePermissionLevel = Field(
        default=QueuePermissionLevel.read,
        sa_column=Column(
            SQLEnum(
                QueuePermissionLevel,
                name="queue_permission_level",
                create_type=False,
            ),
            nullable=False,
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    queue: Optional[Queue] = Relationship(back_populates="role_permissions")
    role: Optional["InitiativeRoleModel"] = Relationship()


class QueueItemDocument(SQLModel, table=True):
    """Junction table linking queue items to documents."""
    __tablename__ = "queue_item_documents"

    queue_item_id: int = Field(foreign_key="queue_items.id", primary_key=True)
    document_id: int = Field(foreign_key="documents.id", primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False)
    attached_by_id: Optional[int] = Field(default=None, foreign_key="users.id", nullable=True)
    attached_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    queue_item: Optional[QueueItem] = Relationship(back_populates="document_links")
    document: Optional["Document"] = Relationship(back_populates="queue_item_links")


class QueueItemTask(SQLModel, table=True):
    """Junction table linking queue items to tasks."""
    __tablename__ = "queue_item_tasks"

    queue_item_id: int = Field(foreign_key="queue_items.id", primary_key=True)
    task_id: int = Field(foreign_key="tasks.id", primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False)
    attached_by_id: Optional[int] = Field(default=None, foreign_key="users.id", nullable=True)
    attached_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    queue_item: Optional[QueueItem] = Relationship(back_populates="task_links")
    task: Optional["Task"] = Relationship(back_populates="queue_item_links")
