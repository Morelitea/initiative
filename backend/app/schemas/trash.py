from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


EntityType = Literal[
    "project",
    "task",
    "document",
    "comment",
    "initiative",
    "tag",
    "queue",
    "queue_item",
    "calendar_event",
]


class TrashItem(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    entity_type: EntityType
    entity_id: int
    name: str
    deleted_at: datetime
    deleted_by_id: Optional[int] = None
    deleted_by_display: str
    purge_at: Optional[datetime] = None


class TrashListResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[TrashItem]
    total: int
    retention_days: Optional[int] = None


class RestoreRequest(BaseModel):
    new_owner_id: Optional[int] = None


class RestoreNeedsReassignmentResponse(BaseModel):
    """409 payload when the entity's owner is no longer an active member of
    the relevant initiative. The client opens a picker seeded with
    ``valid_owner_ids`` and resubmits with the chosen one."""

    needs_reassignment: Literal[True] = True
    valid_owner_ids: list[int]
    detail: str = "TRASH_NEEDS_REASSIGNMENT"
