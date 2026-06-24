"""Schemas for the polymorphic recent-views API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import ConfigDict

from app.schemas.base import SanitizedBaseModel


RecentEntityType = Literal["project", "document", "queue", "counter_group"]


class RecentViewWrite(SanitizedBaseModel):
    """Response body for POST .../{id}/view, common across entity types."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    entity_type: RecentEntityType
    entity_id: int
    last_viewed_at: datetime


class RecentItemRead(SanitizedBaseModel):
    """One entry in the user's recent-items bar.

    Denormalized: contains enough information to render an entity-specific
    icon and link without an N+1 fetch per entity type.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    entity_type: RecentEntityType
    entity_id: int
    guild_id: int
    name: str
    last_viewed_at: datetime
    # Projects: emoji string stored on the project itself.
    icon: Optional[str] = None
    # Documents: drive entity-specific icon + color via getDocumentIcon().
    document_type: Optional[str] = None
    mime_type: Optional[str] = None
    original_filename: Optional[str] = None
