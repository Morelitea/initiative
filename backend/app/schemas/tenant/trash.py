from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import ConfigDict

from app.core.tools import TRASH_TARGETS
from app.schemas.base import SanitizedBaseModel


# Derived from the Tool enum plus the non-tool trashable extras, exactly the way
# TagTarget derives from TAG_TARGETS — a new tool reaches the trash can without
# this being edited.
EntityType = Enum("EntityType", {name: name for name in TRASH_TARGETS}, type=str)
EntityType.__doc__ = "Entity types the trash can holds."


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


class RestoreResponse(SanitizedBaseModel):
    """200 payload for a successful restore. The needs-reassignment case is a
    409 with :class:`RestoreNeedsReassignmentResponse` instead."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    restored: bool
