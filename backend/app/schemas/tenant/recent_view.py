"""Schemas for the polymorphic recent-views API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import AliasChoices, ConfigDict, Field

from app.core.tools import CONTENT_KINDS
from app.models.tenant.recent_view import RECENT_TAB_TYPES, ViewSource
from app.schemas.base import SanitizedBaseModel


# As str enums so FastAPI validates path params and OpenAPI lists the values:
# what becomes a tab (the tools), and every kind opening one records.
RecentEntityType = Enum(
    "RecentEntityType", [(k, k) for k in RECENT_TAB_TYPES], type=str
)
RecentKind = Enum("RecentKind", [(k, k) for k in CONTENT_KINDS], type=str)


class RecentViewWrite(SanitizedBaseModel):
    """Response body for recording an open, common across kinds."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    entity_type: RecentKind
    entity_id: int
    last_viewed_at: datetime
    source: ViewSource


class RecentItemRead(SanitizedBaseModel):
    """One entry in the user's recent-items bar.

    Denormalized: contains enough information to render an entity-specific
    icon and link without an N+1 fetch per entity type.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    entity_type: RecentEntityType
    entity_id: int
    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    # The initiative the entity lives in, which its URL addresses. NULL for a
    # guild-level entity — only calendars have any — which keeps a guild route.
    initiative_id: Optional[int] = None
    name: str
    last_viewed_at: datetime
    # Projects: emoji string stored on the project itself.
    icon: Optional[str] = None
    # Files: drive entity-specific icon + color via fileIcon().
    file_type: Optional[str] = None
    mime_type: Optional[str] = None
    original_filename: Optional[str] = None
