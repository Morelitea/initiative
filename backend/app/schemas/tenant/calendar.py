from __future__ import annotations

from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel

from app.models.tenant.calendar import DEFAULT_CALENDAR_COLOR
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.tag import TagSummary, tag_summaries

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.calendar import Calendar


class CalendarBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    # The calendar's display color — its events render in it. Every calendar
    # has one: creates default it, and the column is NOT NULL.
    color: str = Field(default=DEFAULT_CALENDAR_COLOR, max_length=32)


class CalendarCreate(CalendarBase):
    #: Which initiative the calendar belongs to, or ``None`` for a guild
    #: calendar — one that belongs to the guild itself, the way the calendar
    #: app's own does. Guild scope answers to no initiative's roles or feature
    #: switch; its grants decide who reads and writes it.
    initiative_id: Optional[int] = None
    tag_ids: Optional[List[int]] = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # Defaults to Viewer for all initiative members, which at guild scope reads
    # as every member of the guild.
    grants: List[ResourceGrantSchema] = Field(
        default_factory=lambda: [
            ResourceGrantSchema(all_initiative_members=True, level="read")
        ]
    )


class CalendarUpdate(SanitizedBaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    # Absent = unchanged; a null is rejected (a calendar always has a color).
    color: Optional[str] = Field(default=None, min_length=1, max_length=32)


class CalendarSummary(CalendarBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    #: NULL on a guild-level calendar — one an app mounted, belonging to the
    #: guild rather than to any initiative.
    initiative_id: Optional[int] = None
    guild_id: int
    created_by: int
    created_at: datetime
    updated_at: datetime
    my_permission_level: Optional[str] = None
    tags: List[TagSummary] = Field(default_factory=list)
    # The full sharing state — every resource_grants row for this calendar.
    # Exposed on the summary so the calendar list panel can manage sharing
    # without a per-calendar detail fetch.
    grants: List[ResourceGrantSchema] = Field(default_factory=list)


class CalendarListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[CalendarSummary]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class CalendarRead(CalendarSummary):
    pass


def serialize_calendar_summary(
    calendar: "Calendar", *, user_id: Optional[int] = None
) -> CalendarSummary:
    # Local import avoids a schema -> service import cycle.
    from app.services.permissions import compute_calendar_permission, serialize_grants

    return CalendarSummary(
        id=calendar.id,
        name=calendar.name,
        description=calendar.description,
        color=calendar.color,
        initiative_id=calendar.initiative_id,
        guild_id=calendar.guild_id,
        created_by=calendar.created_by,
        created_at=calendar.created_at,
        updated_at=calendar.updated_at,
        my_permission_level=(
            compute_calendar_permission(calendar, user_id)
            if user_id is not None
            else None
        ),
        tags=tag_summaries(getattr(calendar, "tag_links", None)),
        grants=serialize_grants(calendar),
    )


def serialize_calendar(
    calendar: "Calendar", *, user_id: Optional[int] = None
) -> CalendarRead:
    summary = serialize_calendar_summary(calendar, user_id=user_id)
    return CalendarRead(**summary.model_dump())
