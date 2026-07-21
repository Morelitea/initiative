from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import ConfigDict

from app.schemas.base import SanitizedBaseModel


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
    "counter_group",
    "counter",
    "advanced_tool",
]


class TrashItem(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    entity_type: EntityType
    entity_id: int
    # The guild the entity lives in. Within a single guild's trash this is
    # constant, but the cross-guild ``/me/trash`` view merges several guilds,
    # so the client needs it to address restore/purge (which are guild-scoped).
    guild_id: int
    name: str
    deleted_at: datetime
    deleted_by_id: Optional[int] = None
    deleted_by_display: str
    purge_at: Optional[datetime] = None


class TrashListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[TrashItem]
    total: int
    retention_days: Optional[int] = None


class RestoreRequest(SanitizedBaseModel):
    new_owner_id: Optional[int] = None


class RestoreOwnerCandidate(SanitizedBaseModel):
    """A user eligible to become the restored entity's owner. Carries the
    display name so the picker needn't fetch the whole guild roster."""

    id: int
    full_name: Optional[str] = None


class RestoreNeedsReassignmentResponse(SanitizedBaseModel):
    """409 payload when the entity's owner is no longer an active member of
    the relevant initiative. The client opens a picker seeded with
    ``valid_owners`` and resubmits with the chosen one. ``valid_owner_ids``
    is retained as the bare-id form for validation/back-compat."""

    needs_reassignment: Literal[True] = True
    valid_owner_ids: list[int]
    valid_owners: list[RestoreOwnerCandidate] = []
    detail: str = "TRASH_NEEDS_REASSIGNMENT"
