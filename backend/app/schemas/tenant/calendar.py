from __future__ import annotations

from typing import List, Optional

from pydantic import Field

from app.schemas.base import SanitizedBaseModel, TitleStr
from app.schemas.query import PageMeta

from app.models.tenant.calendar import DEFAULT_CALENDAR_COLOR
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.tenant.tool import ToolSummaryBase


class CalendarBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    # The calendar's display color — its events render in it. Every calendar
    # has one: creates default it, and the column is NOT NULL.
    color: str = Field(default=DEFAULT_CALENDAR_COLOR, max_length=32)


class CalendarCreate(CalendarBase):
    name: TitleStr = Field(..., min_length=1, max_length=255)
    #: Which initiative the calendar belongs to, or ``None`` for a guild
    #: calendar — one that belongs to the guild itself, the way the calendar
    #: app's own does. Guild scope answers to no initiative's roles or feature
    #: switch; its grants decide who reads and writes it.
    initiative_id: Optional[int] = None
    tag_ids: Optional[List[int]] = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # Defaults to Viewer for all initiative members, which at guild scope reads
    # as every member of the guild.
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class CalendarUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    # Absent = unchanged; a null is rejected (a calendar always has a color).
    color: Optional[str] = Field(default=None, min_length=1, max_length=32)


class CalendarSummary(CalendarBase, ToolSummaryBase):
    #: NULL on a guild-level calendar — one an app mounted, belonging to the
    #: guild rather than to any initiative.
    initiative_id: Optional[int] = None


class CalendarListResponse(PageMeta):
    items: List[CalendarSummary]


class CalendarRead(CalendarSummary):
    pass
