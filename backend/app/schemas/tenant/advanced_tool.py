"""Advanced tool schemas — CRUD payloads for the automation tools.

The external automation service (and any in-app UI) reads/writes an advanced tool
through these. ``data`` is the machine-defined automation definition, stored as
jsonb and opaque to us — it is a ``dict`` field, so ``SanitizedBaseModel`` leaves
it untouched (it only strips HTML from top-level ``str`` fields), which is what we
want: sanitizing an automation payload would corrupt URLs/code inside it. ``name``
is a plain-text field and is sanitized.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel
from app.schemas.tenant.resource_grant import ResourceGrantSchema


class AdvancedToolBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    # The automation definition — opaque to us, interpreted by the external
    # service. A dict (JSON object), so it is never HTML-sanitized.
    data: dict[str, Any] = Field(default_factory=dict)


class AdvancedToolCreate(AdvancedToolBase):
    # None → guild-wide (admin-only). Set → initiative-scoped (needs
    # advanced_tool_enabled + the create permission, like other tools).
    initiative_id: Optional[int] = None
    # Initial sharing for an initiative-scoped tool (ignored for guild-wide ones —
    # those are admin-only and can't hold grants). Defaults to Viewer for all
    # initiative members.
    grants: List[ResourceGrantSchema] = Field(
        default_factory=lambda: [
            ResourceGrantSchema(all_initiative_members=True, level="read")
        ]
    )


class AdvancedToolUpdate(SanitizedBaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    data: Optional[dict[str, Any]] = None


class AdvancedToolRead(AdvancedToolBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    # None for a guild-wide tool.
    initiative_id: Optional[int] = None
    guild_id: int
    created_by_id: int
    my_permission_level: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    grants: List[ResourceGrantSchema] = Field(default_factory=list)


class AdvancedToolListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[AdvancedToolRead]
    total_count: int
    page: int
    page_size: int
    has_next: bool


def serialize_advanced_tool(
    tool: "Any",
    *,
    my_permission_level: Optional[str] = None,
) -> AdvancedToolRead:
    # Local import avoids a schema -> service import cycle.
    from app.services.permissions import serialize_grants

    return AdvancedToolRead(
        id=tool.id,
        name=tool.name,
        data=tool.data,
        initiative_id=tool.initiative_id,
        guild_id=tool.guild_id,
        created_by_id=tool.created_by_id,
        my_permission_level=my_permission_level,
        created_at=tool.created_at,
        updated_at=tool.updated_at,
        grants=serialize_grants(tool),
    )
