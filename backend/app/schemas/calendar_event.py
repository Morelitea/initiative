from __future__ import annotations

from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.calendar_event import RSVPStatus
from app.schemas.tag import TagSummary
from app.schemas.user import UserPublic

if TYPE_CHECKING:  # pragma: no cover
    from app.models.calendar_event import CalendarEvent


# ---------------------------------------------------------------------------
# Attendee schemas
# ---------------------------------------------------------------------------


class CalendarEventAttendeeCreate(BaseModel):
    user_id: int


class CalendarEventAttendeeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    user_id: int
    user: Optional[UserPublic] = None
    rsvp_status: RSVPStatus
    created_at: datetime


class CalendarEventRSVPUpdate(BaseModel):
    rsvp_status: RSVPStatus


# ---------------------------------------------------------------------------
# Document attachment read schema
# ---------------------------------------------------------------------------


class CalendarEventDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    title: str = ""
    attached_at: datetime


# ---------------------------------------------------------------------------
# Recurrence schema
# ---------------------------------------------------------------------------


class EventRecurrence(BaseModel):
    frequency: str = Field(..., pattern="^(daily|weekly|monthly|yearly)$")
    interval: int = Field(default=1, ge=1, le=365)
    weekdays: Optional[List[str]] = None
    monthly_mode: Optional[str] = Field(default=None, pattern="^(day_of_month|weekday)$")
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    weekday_position: Optional[str] = Field(
        default=None, pattern="^(first|second|third|fourth|last)$"
    )
    weekday: Optional[str] = None
    month: Optional[int] = Field(default=None, ge=1, le=12)
    ends: str = Field(default="never", pattern="^(never|on_date|after_occurrences)$")
    end_after_occurrences: Optional[int] = Field(default=None, ge=1, le=1000)
    end_date: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Calendar event schemas
# ---------------------------------------------------------------------------


class CalendarEventBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=500)
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    color: Optional[str] = None
    recurrence: Optional[EventRecurrence] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "CalendarEventBase":
        if self.end_at < self.start_at:
            raise ValueError("end_at must be after start_at")
        # Non-all-day events cannot span more than 24 hours
        if not self.all_day:
            from datetime import timedelta
            if (self.end_at - self.start_at) > timedelta(hours=24):
                raise ValueError("Non-all-day events cannot span more than 24 hours")
        return self


class CalendarEventCreate(CalendarEventBase):
    initiative_id: int
    attendee_ids: Optional[List[int]] = None
    tag_ids: Optional[List[int]] = None
    document_ids: Optional[List[int]] = None


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=500)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    all_day: Optional[bool] = None
    color: Optional[str] = None
    recurrence: Optional[EventRecurrence] = None


class CalendarEventSummary(CalendarEventBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    initiative_id: int
    guild_id: int
    created_by_id: int
    attendee_count: int = 0
    attendee_names: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CalendarEventListResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[CalendarEventSummary]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class CalendarEventRead(CalendarEventSummary):
    attendees: List[CalendarEventAttendeeRead] = Field(default_factory=list)
    tags: List[TagSummary] = Field(default_factory=list)
    documents: List[CalendarEventDocumentRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_tags(event: "CalendarEvent") -> List[TagSummary]:
    tag_links = getattr(event, "tag_links", None) or []
    tags: List[TagSummary] = []
    for link in tag_links:
        tag = getattr(link, "tag", None)
        if tag:
            tags.append(TagSummary(id=tag.id, name=tag.name, color=tag.color))
    return tags


def _serialize_documents(event: "CalendarEvent") -> List[CalendarEventDocumentRead]:
    doc_links = getattr(event, "document_links", None) or []
    result: List[CalendarEventDocumentRead] = []
    for link in doc_links:
        doc = getattr(link, "document", None)
        result.append(CalendarEventDocumentRead(
            document_id=link.document_id,
            title=getattr(doc, "title", "") if doc else "",
            attached_at=link.attached_at,
        ))
    return result


def _serialize_attendees(event: "CalendarEvent") -> List[CalendarEventAttendeeRead]:
    attendees_list = getattr(event, "attendees", None) or []
    result: List[CalendarEventAttendeeRead] = []
    for att in attendees_list:
        user = getattr(att, "user", None)
        result.append(CalendarEventAttendeeRead(
            user_id=att.user_id,
            user=UserPublic.model_validate(user) if user else None,
            rsvp_status=att.rsvp_status,
            created_at=att.created_at,
        ))
    return result


def _parse_recurrence(event: "CalendarEvent") -> Optional[EventRecurrence]:
    raw = getattr(event, "recurrence", None)
    if not raw:
        return None
    import json
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return EventRecurrence(**data)
    except Exception:
        return None


def serialize_calendar_event_summary(event: "CalendarEvent") -> CalendarEventSummary:
    attendees_list = getattr(event, "attendees", None) or []
    names: List[str] = []
    for att in attendees_list:
        user = getattr(att, "user", None)
        if user:
            names.append(user.full_name or user.email)
    return CalendarEventSummary(
        id=event.id,
        title=event.title,
        description=event.description,
        location=event.location,
        start_at=event.start_at,
        end_at=event.end_at,
        all_day=event.all_day,
        color=event.color,
        recurrence=_parse_recurrence(event),
        initiative_id=event.initiative_id,
        guild_id=event.guild_id,
        created_by_id=event.created_by_id,
        attendee_count=len(attendees_list),
        attendee_names=names,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def serialize_calendar_event(event: "CalendarEvent") -> CalendarEventRead:
    summary = serialize_calendar_event_summary(event)
    return CalendarEventRead(
        **summary.model_dump(),
        attendees=_serialize_attendees(event),
        tags=_serialize_tags(event),
        documents=_serialize_documents(event),
    )
