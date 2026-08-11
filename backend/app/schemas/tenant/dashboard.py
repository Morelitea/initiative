from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel

from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.tag import TagSummary, tag_summaries
from app.services.tenant.dashboard_definition import (
    ALL_SOURCES,
    WIDGET_PRESETS,
    WIDGET_SPECS,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.dashboard import Dashboard


# Derived from the widget registry rather than restated, the way TagTarget
# derives from TAG_TARGETS: a new primitive reaches the API — and, through the
# generated types, the frontend's drift test — without an edit here.
WidgetType = Enum("WidgetType", {name: name for name in sorted(WIDGET_SPECS)}, type=str)
WidgetType.__doc__ = "Widget primitives this build has renderers for."

BindingSource = Enum(
    "BindingSource", {name: name for name in sorted(ALL_SOURCES)}, type=str
)
BindingSource.__doc__ = "Data sources a widget binding may name."


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


# --- widget catalog --------------------------------------------------------
#
# What the editor's palette needs to know about each widget: how small it may
# be placed, what it can bind to, and which display options it takes. It is a
# projection of WIDGET_SPECS, served rather than duplicated, so the frontend
# never carries a second copy of the vocabulary.


class WidgetOption(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    key: str
    values: List[str]


class WidgetCatalogEntry(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    type: WidgetType  # type: ignore[valid-type]
    min_w: int
    min_h: int
    default_w: int
    default_h: int
    sources: List[BindingSource]  # type: ignore[valid-type]
    options: List[WidgetOption] = Field(default_factory=list)


class WidgetPresetEntry(SanitizedBaseModel):
    """A named widget built from a primitive plus fixed options — the palette's
    ready-made entries ("Bar chart"), and later the shape a listing uses to
    contribute its own."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    name: str
    primitive: WidgetType  # type: ignore[valid-type]
    options: Dict[str, str] = Field(default_factory=dict)


class WidgetCatalog(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    widgets: List[WidgetCatalogEntry]
    presets: List[WidgetPresetEntry]


def build_widget_catalog() -> WidgetCatalog:
    return WidgetCatalog(
        widgets=[
            WidgetCatalogEntry(
                type=name,
                min_w=spec.min_w,
                min_h=spec.min_h,
                default_w=spec.default_w,
                default_h=spec.default_h,
                sources=sorted(spec.sources),
                options=[
                    WidgetOption(key=key, values=sorted(values))
                    for key, values in sorted(spec.options.items())
                ],
            )
            for name, spec in sorted(WIDGET_SPECS.items())
        ],
        presets=[
            WidgetPresetEntry(
                name=name,
                primitive=preset.primitive,
                options=dict(preset.options),
            )
            for name, preset in sorted(WIDGET_PRESETS.items())
        ],
    )


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
