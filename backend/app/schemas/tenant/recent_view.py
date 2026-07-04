"""Schemas for the polymorphic recent-views API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import ConfigDict

from app.core.tools import RECENTABLE_TOOLS
from app.schemas.base import SanitizedBaseModel


# Derived from the canonical Tool enum — the recentable tools' string values,
# as a str enum so FastAPI validates path params and OpenAPI lists the values.
RecentEntityType = Enum(
    "RecentEntityType", [(t.value, t.value) for t in RECENTABLE_TOOLS], type=str
)


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
