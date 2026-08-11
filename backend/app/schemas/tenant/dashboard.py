from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel

from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.tag import TagSummary, tag_summaries

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.dashboard import Dashboard


class DashboardBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)


class DashboardCreate(DashboardBase):
    initiative_id: int
    tag_ids: Optional[List[int]] = None
    # The canvas body. Validated + canonicalized by
    # ``dashboard_definition.normalize_dashboard_definition`` before it is
    # stored, so only known widget/binding vocabulary ever lands in the row.
    # Defaults to an empty canvas the author fills in.
    definition: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # Defaults to Viewer for all initiative members.
    grants: List[ResourceGrantSchema] = Field(
        default_factory=lambda: [
            ResourceGrantSchema(all_initiative_members=True, level="read")
        ]
    )


class DashboardUpdate(SanitizedBaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    # Absent = unchanged. Sending either re-runs validation over the pair, so
    # config can never outlive the widgets it configures.
    definition: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None


class DashboardSummary(DashboardBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    initiative_id: int
    guild_id: int
    created_by_id: int
    created_at: datetime
    updated_at: datetime
    # Marketplace provenance; both null for a dashboard authored from scratch.
    listing_uid: Optional[str] = None
    listing_version: Optional[str] = None
    my_permission_level: Optional[str] = None
    tags: List[TagSummary] = Field(default_factory=list)
    grants: List[ResourceGrantSchema] = Field(default_factory=list)


class DashboardListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[DashboardSummary]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class DashboardRead(DashboardSummary):
    # The canvas body is only sent on the detail read — a list of dashboards
    # doesn't render widgets, and definitions are the largest field here.
    definition: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)


def serialize_dashboard_summary(
    dashboard: "Dashboard", *, user_id: Optional[int] = None
) -> DashboardSummary:
    # Local import avoids a schema -> service import cycle.
    from app.services.permissions import compute_dashboard_permission, serialize_grants

    return DashboardSummary(
        id=dashboard.id,
        name=dashboard.name,
        description=dashboard.description,
        initiative_id=dashboard.initiative_id,
        guild_id=dashboard.guild_id,
        created_by_id=dashboard.created_by_id,
        created_at=dashboard.created_at,
        updated_at=dashboard.updated_at,
        listing_uid=dashboard.listing_uid,
        listing_version=dashboard.listing_version,
        my_permission_level=(
            compute_dashboard_permission(dashboard, user_id)
            if user_id is not None
            else None
        ),
        tags=tag_summaries(getattr(dashboard, "tag_links", None)),
        grants=serialize_grants(dashboard),
    )


def serialize_dashboard(
    dashboard: "Dashboard", *, user_id: Optional[int] = None
) -> DashboardRead:
    summary = serialize_dashboard_summary(dashboard, user_id=user_id)
    return DashboardRead(
        **summary.model_dump(),
        definition=dashboard.definition or {},
        config=dashboard.config or {},
    )
