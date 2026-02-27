from __future__ import annotations

from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.models.queue import QueuePermissionLevel
from app.schemas.tag import TagSummary
from app.schemas.user import UserPublic

if TYPE_CHECKING:  # pragma: no cover
    from app.models.queue import Queue, QueueItem


# ---------------------------------------------------------------------------
# Permission schemas (declared first so Queue schemas can reference them)
# ---------------------------------------------------------------------------


class QueuePermissionCreate(BaseModel):
    user_id: int
    level: QueuePermissionLevel = QueuePermissionLevel.write


class QueuePermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    user_id: int
    level: QueuePermissionLevel
    created_at: datetime


class QueueRolePermissionCreate(BaseModel):
    initiative_role_id: int
    level: QueuePermissionLevel = QueuePermissionLevel.read


class QueueRolePermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    initiative_role_id: int
    role_name: str = ""
    role_display_name: str = ""
    level: QueuePermissionLevel
    created_at: datetime


# ---------------------------------------------------------------------------
# Queue item attachment read schemas
# ---------------------------------------------------------------------------


class QueueItemDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    title: str = ""
    attached_at: datetime


class QueueItemTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: int
    title: str = ""
    attached_at: datetime


# ---------------------------------------------------------------------------
# Queue item schemas
# ---------------------------------------------------------------------------


class QueueItemBase(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    position: int = 0
    color: Optional[str] = None
    notes: Optional[str] = None
    is_visible: bool = True


class QueueItemCreate(QueueItemBase):
    user_id: Optional[int] = None
    tag_ids: Optional[List[int]] = None
    document_ids: Optional[List[int]] = None
    task_ids: Optional[List[int]] = None


class QueueItemUpdate(BaseModel):
    label: Optional[str] = None
    position: Optional[int] = None
    user_id: Optional[int] = None
    color: Optional[str] = None
    notes: Optional[str] = None
    is_visible: Optional[bool] = None


class QueueItemRead(QueueItemBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    queue_id: int
    user_id: Optional[int] = None
    user: Optional[UserPublic] = None
    tags: List[TagSummary] = Field(default_factory=list)
    documents: List[QueueItemDocumentRead] = Field(default_factory=list)
    tasks: List[QueueItemTaskRead] = Field(default_factory=list)
    created_at: datetime


class QueueItemReorderRequest(BaseModel):
    class ReorderItem(BaseModel):
        id: int
        position: int

    items: List[ReorderItem]


# ---------------------------------------------------------------------------
# Queue schemas
# ---------------------------------------------------------------------------


class QueueBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class QueueCreate(QueueBase):
    initiative_id: int
    role_permissions: Optional[List[QueueRolePermissionCreate]] = None
    user_permissions: Optional[List[QueuePermissionCreate]] = None


class QueueUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class QueueSummary(QueueBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

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


class QueueListResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[QueueSummary]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class QueueRead(QueueSummary):
    items: List[QueueItemRead] = Field(default_factory=list)
    current_item: Optional[QueueItemRead] = None
    permissions: List[QueuePermissionRead] = Field(default_factory=list)
    role_permissions: List[QueueRolePermissionRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_queue_item_tags(item: "QueueItem") -> List[TagSummary]:
    tag_links = getattr(item, "tag_links", None) or []
    tags: List[TagSummary] = []
    for link in tag_links:
        tag = getattr(link, "tag", None)
        if tag:
            tags.append(TagSummary(id=tag.id, name=tag.name, color=tag.color))
    return tags


def _serialize_queue_item_documents(item: "QueueItem") -> List[QueueItemDocumentRead]:
    doc_links = getattr(item, "document_links", None) or []
    result: List[QueueItemDocumentRead] = []
    for link in doc_links:
        doc = getattr(link, "document", None)
        result.append(QueueItemDocumentRead(
            document_id=link.document_id,
            title=getattr(doc, "title", "") if doc else "",
            attached_at=link.attached_at,
        ))
    return result


def _serialize_queue_item_tasks(item: "QueueItem") -> List[QueueItemTaskRead]:
    task_links = getattr(item, "task_links", None) or []
    result: List[QueueItemTaskRead] = []
    for link in task_links:
        task = getattr(link, "task", None)
        result.append(QueueItemTaskRead(
            task_id=link.task_id,
            title=getattr(task, "title", "") if task else "",
            attached_at=link.attached_at,
        ))
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
        tags=_serialize_queue_item_tags(item),
        documents=_serialize_queue_item_documents(item),
        tasks=_serialize_queue_item_tasks(item),
        created_at=item.created_at,
    )


def _serialize_permissions(queue: "Queue") -> List[QueuePermissionRead]:
    permissions = getattr(queue, "permissions", None) or []
    return [
        QueuePermissionRead(user_id=p.user_id, level=p.level, created_at=p.created_at)
        for p in permissions
    ]


def _serialize_role_permissions(queue: "Queue") -> List[QueueRolePermissionRead]:
    role_permissions = getattr(queue, "role_permissions", None) or []
    result: List[QueueRolePermissionRead] = []
    for rp in role_permissions:
        role = getattr(rp, "role", None)
        result.append(QueueRolePermissionRead(
            initiative_role_id=rp.initiative_role_id,
            role_name=getattr(role, "name", "") if role else "",
            role_display_name=getattr(role, "display_name", "") if role else "",
            level=rp.level,
            created_at=rp.created_at,
        ))
    return result


def serialize_queue_summary(
    queue: "Queue",
    *,
    my_permission_level: Optional[str] = None,
) -> QueueSummary:
    items = getattr(queue, "items", None) or []
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
        permissions=_serialize_permissions(queue),
        role_permissions=_serialize_role_permissions(queue),
    )
