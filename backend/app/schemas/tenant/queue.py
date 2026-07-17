from __future__ import annotations

from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from pydantic import ConfigDict, Field

from app.schemas.base import RichTextStr, SanitizedBaseModel

from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.tag import TagSummary, tag_summaries
from app.schemas.platform.user import UserPublic

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.queue import Queue, QueueItem


# ---------------------------------------------------------------------------
# Queue item attachment read schemas
# ---------------------------------------------------------------------------


class QueueItemDocumentRead(SanitizedBaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    title: str = ""
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
    user_id: Optional[int] = None
    tag_ids: Optional[List[int]] = None
    document_ids: Optional[List[int]] = None
    task_ids: Optional[List[int]] = None


class QueueItemUpdate(SanitizedBaseModel):
    label: Optional[str] = None
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
    initiative_id: int
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # Defaults to Viewer for all initiative members.
    grants: List[ResourceGrantSchema] = Field(
        default_factory=lambda: [
            ResourceGrantSchema(all_initiative_members=True, level="read")
        ]
    )


class QueueUpdate(SanitizedBaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class QueueSummary(QueueBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    initiative_id: int
    guild_id: int
    created_by_id: int
    current_round: int
    is_active: bool
    item_count: int = 0
    created_at: datetime
    updated_at: datetime
    my_permission_level: Optional[str] = None
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


def _serialize_queue_item_documents(item: "QueueItem") -> List[QueueItemDocumentRead]:
    doc_links = getattr(item, "document_links", None) or []
    result: List[QueueItemDocumentRead] = []
    for link in doc_links:
        doc = getattr(link, "document", None)
        result.append(
            QueueItemDocumentRead(
                document_id=link.document_id,
                title=getattr(doc, "title", "") if doc else "",
                attached_at=link.attached_at,
            )
        )
    return result


def _serialize_queue_item_tasks(item: "QueueItem") -> List[QueueItemTaskRead]:
    task_links = getattr(item, "task_links", None) or []
    result: List[QueueItemTaskRead] = []
    for link in task_links:
        task = getattr(link, "task", None)
        result.append(
            QueueItemTaskRead(
                task_id=link.task_id,
                title=getattr(task, "title", "") if task else "",
                attached_at=link.attached_at,
            )
        )
    return result


def serialize_queue_item(item: "QueueItem") -> QueueItemRead:
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
        tags=tag_summaries(getattr(item, "tag_links", None)),
        documents=_serialize_queue_item_documents(item),
        tasks=_serialize_queue_item_tasks(item),
        created_at=item.created_at,
    )


def serialize_queue_summary(
    queue: "Queue",
    *,
    my_permission_level: Optional[str] = None,
) -> QueueSummary:
    items = getattr(queue, "items", None) or []
    # Local import avoids a schema -> service import cycle.
    from app.services.permissions import serialize_grants

    return QueueSummary(
        id=queue.id,
        name=queue.name,
        description=queue.description,
        initiative_id=queue.initiative_id,
        guild_id=queue.guild_id,
        created_by_id=queue.created_by_id,
        current_round=queue.current_round,
        is_active=queue.is_active,
        item_count=len(items),
        created_at=queue.created_at,
        updated_at=queue.updated_at,
        my_permission_level=my_permission_level,
        tags=tag_summaries(getattr(queue, "tag_links", None)),
        grants=serialize_grants(queue),
    )


def serialize_queue(
    queue: "Queue",
    *,
    my_permission_level: Optional[str] = None,
) -> QueueRead:
    items = getattr(queue, "items", None) or []
    serialized_items = [serialize_queue_item(item) for item in items]
    current_item = None
    if queue.current_item_id:
        for item in serialized_items:
            if item.id == queue.current_item_id:
                current_item = item
                break
    summary = serialize_queue_summary(queue, my_permission_level=my_permission_level)
    return QueueRead(
        **summary.model_dump(),
        items=serialized_items,
        current_item=current_item,
    )
