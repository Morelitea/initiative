from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import ConfigDict

from app.core.tools import TRASH_TARGETS
from app.schemas.base import SanitizedBaseModel


# Derived from the Tool enum plus the non-tool trashable extras, the same way
# TagTarget derives from TAG_TARGETS — a new tool reaches the trash can without
# this being edited. ``trash_test`` asserts ENTITY_REGISTRY covers every target.
EntityType = Literal[TRASH_TARGETS]  # type: ignore[valid-type]


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


class RestoreResponse(SanitizedBaseModel):
    """200 payload for a successful restore. The needs-reassignment case is a
    409 with :class:`RestoreNeedsReassignmentResponse` instead."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    restored: bool


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
