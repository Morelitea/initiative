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

from app.schemas.base import RawTextStr, SanitizedBaseModel
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.tag import TagSummary, tag_summaries


class AdvancedToolBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    # The automation definition — opaque to us, interpreted by the external
    # service. A dict (JSON object), so it is never HTML-sanitized.
    data: dict[str, Any] = Field(default_factory=dict)


class AdvancedToolCreate(AdvancedToolBase):
    # None → guild-wide (admin-only). Set → initiative-scoped (needs
    # advanced_tools_enabled + the create permission, like other tools).
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
    tags: List[TagSummary] = Field(default_factory=list)
    grants: List[ResourceGrantSchema] = Field(default_factory=list)


class AdvancedToolRunRequest(SanitizedBaseModel):
    # These three are opaque machine identifiers: echoed straight back to the
    # runner, and node_key indexes into the (never-sanitized) definition blob.
    # RawTextStr so HTML stripping can't silently mangle a value that contains
    # markup characters — the max_length caps still bound the input.
    # node_key names the flow entry being fired (None = the default entry).
    node_key: Optional[RawTextStr] = Field(default=None, max_length=255)
    # Provenance for the run log (e.g. "schedule", "event").
    cause: Optional[RawTextStr] = Field(default=None, max_length=64)
    source_event_id: Optional[RawTextStr] = Field(default=None, max_length=255)


class AdvancedToolRunResult(SanitizedBaseModel):
    # Success is the HTTP status: a 200 body is always a completed run (the
    # runner treats 404 as "tool gone" and 403 as retriable), so there is no
    # ``ok`` flag to carry.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    advanced_tool_id: int
    guild_id: int
    initiative_id: Optional[int] = None
    # Echoed verbatim from the request — RawTextStr for the same reason.
    node_key: Optional[RawTextStr] = None
    cause: Optional[RawTextStr] = None
    source_event_id: Optional[RawTextStr] = None
    # The tool's current definition — the caller interprets it, we don't.
    data: dict[str, Any] = Field(default_factory=dict)
    ran_at: datetime


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
        tags=tag_summaries(getattr(tool, "tag_links", None)),
        grants=serialize_grants(tool),
    )
