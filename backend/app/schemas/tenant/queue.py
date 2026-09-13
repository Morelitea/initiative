from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence, TYPE_CHECKING

from pydantic import ConfigDict, Field

from app.core.relationships import Related
from app.core.tools import Tool
from app.schemas.base import RichTextStr, SanitizedBaseModel, TitleStr
from app.schemas.tenant.archive import ArchiveState

from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.tag import TagSummary, annotated_tags
from app.schemas.platform.user import UserPublic

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.queue import Queue, QueueItem


# ---------------------------------------------------------------------------
# Queue item attachment read schemas
# ---------------------------------------------------------------------------


class QueueItemDocumentRead(SanitizedBaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    name: str = ""
    attached_at: datetime


class QueueItemTaskRead(SanitizedBaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: int
    title: str = ""
    attached_at: datetime


# ---------------------------------------------------------------------------
# Queue item schemas
# ---------------------------------------------------------------------------


class QueueItemBase(SanitizedBaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    position: float = 0.0
    color: Optional[str] = None
    notes: Optional[RichTextStr] = None
    is_visible: bool = True


class QueueItemCreate(QueueItemBase):
    label: TitleStr = Field(..., min_length=1, max_length=255)
    user_id: Optional[int] = None
    tag_ids: Optional[List[int]] = None
    document_ids: Optional[List[int]] = None
    task_ids: Optional[List[int]] = None


class QueueItemUpdate(SanitizedBaseModel):
    label: Optional[TitleStr] = None
    position: Optional[float] = None
    user_id: Optional[int] = None
    color: Optional[str] = None
    notes: Optional[RichTextStr] = None
    is_visible: Optional[bool] = None


class QueueItemRead(QueueItemBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    queue_id: int
    user_id: Optional[int] = None
    user: Optional[UserPublic] = None
    tags: List[TagSummary] = Field(default_factory=list)
    documents: List[QueueItemDocumentRead] = Field(default_factory=list)
    tasks: List[QueueItemTaskRead] = Field(default_factory=list)
    # Round in which the user held this item (NULL = not held). The rotation
    # auto-releases the item at its natural slot in ``held_at_round + 1`` so
    # held participants can't be forgotten.
    held_at_round: Optional[int] = None
    created_at: datetime


class QueueItemReorderRequest(SanitizedBaseModel):
    class ReorderItem(SanitizedBaseModel):
        id: int
        position: float

    items: List[ReorderItem]


class QueueReleaseRequest(SanitizedBaseModel):
    """Options for releasing a held queue item back into the rotation."""

    # When True (PF2e "Delay" semantics), the released item's position is
    # rewritten so it lands immediately after the current item in turn order
    # — i.e. they take their delayed turn at this point and stay at this new
    # initiative slot for the rest of the encounter. Default False preserves
    # their original initiative; they re-enter at their natural slot.
    reposition: bool = False


# ---------------------------------------------------------------------------
# Queue schemas
# ---------------------------------------------------------------------------


class QueueBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class QueueCreate(QueueBase):
    name: TitleStr = Field(..., min_length=1, max_length=255)
    initiative_id: int
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # Defaults to Viewer for all initiative members.
    grants: List[ResourceGrantSchema] = Field(
        default_factory=lambda: [
            ResourceGrantSchema(all_initiative_members=True, level="read")
        ]
    )


class QueueUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = None
    description: Optional[str] = None


class QueueSummary(QueueBase, ArchiveState):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    initiative_id: int
    guild_id: int
    created_by: int
    current_round: int
    is_active: bool
    item_count: int = 0
    created_at: datetime
    updated_at: datetime
    my_permission_level: Optional[str] = None
    # When false this entity's comment thread is off — the UI renders none
    # and the API refuses to read or post one. Tasks are unaffected; their
    # thread belongs to the task, not to the tool.
    comments_enabled: bool = True
    tags: List[TagSummary] = Field(default_factory=list)
    # The full sharing state — every resource_grants row for this queue. Exposed on
    # the summary (not just the detail read) so list views can manage sharing in
    # bulk without a per-item detail fetch.
    grants: List[ResourceGrantSchema] = Field(default_factory=list)


class QueueListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[QueueSummary]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class QueueRead(QueueSummary):
    items: List[QueueItemRead] = Field(default_factory=list)
    current_item: Optional[QueueItemRead] = None


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_queue_item_documents(
    documents: Sequence[Related],
) -> List[QueueItemDocumentRead]:
    return [
        QueueItemDocumentRead(
            document_id=related.id,
            name=getattr(related.entity, "name", "") if related.entity else "",
            attached_at=related.linked_at,
        )
        for related in documents
    ]


def _serialize_queue_item_tasks(tasks: Sequence[Related]) -> List[QueueItemTaskRead]:
    return [
        QueueItemTaskRead(
            task_id=related.id,
            title=getattr(related.entity, "title", "") if related.entity else "",
            attached_at=related.linked_at,
        )
        for related in tasks
    ]


def serialize_queue_item(
    item: "QueueItem",
    *,
    documents: Sequence[Related] = (),
    tasks: Sequence[Related] = (),
) -> QueueItemRead:
    """One queue item.

    Attachments are handed in rather than read off the item: they live in their
    own table now, and a queue shows many items at once, so the caller loads
    them for the whole page in one go.
    """
    user = getattr(item, "user", None)
    return QueueItemRead(
        id=item.id,
        queue_id=item.queue_id,
        label=item.label,
        position=item.position,
        user_id=item.user_id,
        user=UserPublic.model_validate(user) if user else None,
        color=item.color,
        notes=item.notes,
        is_visible=item.is_visible,
        held_at_round=item.held_at_round,
        tags=annotated_tags(item),
        documents=_serialize_queue_item_documents(documents),
        tasks=_serialize_queue_item_tasks(tasks),
        created_at=item.created_at,
    )


def serialize_queue_summary(
    queue: "Queue",
    *,
    user_id: Optional[int] = None,
) -> QueueSummary:
    items = getattr(queue, "items", None) or []
    # Local import avoids a schema -> service import cycle.
    from app.services.permissions import client_access, serialize_grants

    return QueueSummary(
        id=queue.id,
        name=queue.name,
        description=queue.description,
        initiative_id=queue.initiative_id,
        guild_id=queue.guild_id,
        created_by=queue.created_by,
        current_round=queue.current_round,
        is_active=queue.is_active,
        item_count=len(items),
        created_at=queue.created_at,
        updated_at=queue.updated_at,
        archived_at=queue.archived_at,
        **client_access(Tool.queue, queue, user_id),
        comments_enabled=queue.comments_enabled,
        tags=annotated_tags(queue),
        grants=serialize_grants(queue),
    )


def serialize_queue(
    queue: "Queue",
    *,
    user_id: Optional[int] = None,
) -> QueueRead:
    items = getattr(queue, "items", None) or []
    serialized_items = [serialize_queue_item(item) for item in items]
    current_item = None
    if queue.current_item_id:
        for item in serialized_items:
            if item.id == queue.current_item_id:
                current_item = item
                break
    summary = serialize_queue_summary(queue, user_id=user_id)
    return QueueRead(
        **summary.model_dump(),
        items=serialized_items,
        current_item=current_item,
    )
