from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence, TYPE_CHECKING

from pydantic import ConfigDict, Field, model_validator

from app.core.identity_boundary import GuildId, PersonId
from app.core.relationships import Related
from app.schemas.base import SanitizedBaseModel, TitleStr
from app.schemas.query import PageMeta

from app.models.tenant.calendar_event import RSVPStatus
from app.schemas.tenant.property import PropertySummary
from app.schemas.tenant.archive import ContentCan
from app.schemas.tenant.tag import TagSummary, annotated_tags
from app.schemas.tenant.tool import from_row
from app.schemas.platform.user import AvatarUrl, UserPublic
from app.core.user_display import display_name

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext
    from app.models.tenant.calendar_event import CalendarEvent


# ---------------------------------------------------------------------------
# Attendee schemas
# ---------------------------------------------------------------------------


class CalendarEventAttendeeRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    user_id: PersonId
    user: Optional[UserPublic] = None
    rsvp_status: RSVPStatus
    created_at: datetime


class CalendarEventRSVPUpdate(SanitizedBaseModel):
    rsvp_status: RSVPStatus


# ---------------------------------------------------------------------------
# Document attachment read schema
# ---------------------------------------------------------------------------


class CalendarEventDocumentRead(SanitizedBaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    name: str = ""
    attached_at: datetime


# ---------------------------------------------------------------------------
# Recurrence schema
# ---------------------------------------------------------------------------


class EventRecurrence(SanitizedBaseModel):
    frequency: str = Field(..., pattern="^(daily|weekly|monthly|yearly)$")
    interval: int = Field(default=1, ge=1, le=365)
    weekdays: Optional[List[str]] = None
    monthly_mode: Optional[str] = Field(
        default=None, pattern="^(day_of_month|weekday)$"
    )
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


class CalendarEventBase(SanitizedBaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=500)
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    recurrence: Optional[EventRecurrence] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "CalendarEventBase":
        if self.end_at < self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class CalendarEventCreate(CalendarEventBase):
    title: TitleStr = Field(..., min_length=1, max_length=255)
    calendar_id: int
    attendee_ids: Optional[List[PersonId]] = None
    tag_ids: Optional[List[int]] = None
    document_ids: Optional[List[int]] = None


class CalendarEventUpdate(SanitizedBaseModel):
    title: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=500)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    all_day: Optional[bool] = None
    recurrence: Optional[EventRecurrence] = None
    # Move the event to another calendar (requires write on both calendars).
    calendar_id: Optional[int] = None


class CalendarEventAttendeePreview(SanitizedBaseModel):
    """Compact per-attendee snapshot for list responses.

    Carries the id + avatar fields the SPA needs to render tinted,
    image-backed avatars on the calendar list view. The full
    ``CalendarEventAttendeeRead`` (with RSVP status + timestamps) is
    still exposed on the detail endpoint.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    user_id: PersonId
    name: str
    avatar_url: AvatarUrl = None


class CalendarEventSummary(CalendarEventBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    calendar_id: int
    # Derived from the parent calendar — kept on the summary so list views can
    # filter/group by initiative without another fetch. NULL when the parent is
    # a guild-level calendar.
    initiative_id: Optional[int] = None
    guild_id: GuildId
    created_by: PersonId | None = None
    attendee_count: int = 0
    attendee_names: List[str] = Field(default_factory=list)
    attendee_previews: List[CalendarEventAttendeePreview] = Field(default_factory=list)
    property_values: List[PropertySummary] = Field(default_factory=list)
    tags: List[TagSummary] = Field(default_factory=list)
    #: What the caller may do to this event — its calendar's edit, since events
    #: hold no grants of their own.
    can: ContentCan = Field(default_factory=ContentCan)
    created_at: datetime
    updated_at: datetime


class CalendarEventListResponse(PageMeta):
    items: List[CalendarEventSummary]


class CalendarEventRead(CalendarEventSummary):
    attendees: List[CalendarEventAttendeeRead] = Field(default_factory=list)
    documents: List[CalendarEventDocumentRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_documents(
    documents: Sequence[Related],
) -> List[CalendarEventDocumentRead]:
    """The attached documents, as the read schema wants them.

    Handed in rather than read off the event: the edges live in their own table
    now, and loading them is the caller's job so a page of events pays for one
    query instead of one per event.
    """
    return [
        CalendarEventDocumentRead(
            document_id=related.id,
            name=getattr(related.entity, "name", "") if related.entity else "",
            attached_at=related.linked_at,
        )
        for related in documents
    ]


def _serialize_attendees(event: "CalendarEvent") -> List[CalendarEventAttendeeRead]:
    attendees_list = getattr(event, "attendees", None) or []
    result: List[CalendarEventAttendeeRead] = []
    for att in attendees_list:
        user = getattr(att, "user", None)
        result.append(
            CalendarEventAttendeeRead(
                user_id=att.user_id,
                user=UserPublic.model_validate(user) if user else None,
                rsvp_status=att.rsvp_status,
                created_at=att.created_at,
            )
        )
    return result


def _serialize_event_properties(event: "CalendarEvent") -> List[PropertySummary]:
    """Serialize loaded event property values.

    Requires ``property_values.property_definition`` (and ``.value_user``
    for user_reference) to be eager-loaded — otherwise they are skipped.
    """
    # Local import avoids the schema layer pulling in the service at
    # module import time.
    from app.services.tenant.properties import summaries_from_rows

    rows = getattr(event, "property_values", None) or []
    return summaries_from_rows(rows)


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


def serialize_calendar_event_summary(
    event: "CalendarEvent",
    *,
    context: ActorContext,
    user_id: Optional[int] = None,
    guild_id: Optional[int] = None,
) -> CalendarEventSummary:
    # Local import avoids a schema -> service import cycle.
    from app.db.guild_standing import InstallContext
    from app.services.permissions import Action, allows

    # Access is inherited from the parent calendar; requires ``event.calendar``
    # eager-loaded with its level. An installed app has no user id and is
    # answered its own level, as ``client_access`` answers it on a calendar.
    calendar = event.calendar
    reader = user_id is not None or isinstance(context, InstallContext)
    can_edit = reader and calendar is not None and allows(calendar, Action.contribute)
    attendees_list = getattr(event, "attendees", None) or []
    names: List[str] = []
    previews: List[CalendarEventAttendeePreview] = []
    for att in attendees_list:
        user = getattr(att, "user", None)
        if user:
            display = display_name(user)
            names.append(display)
            previews.append(
                CalendarEventAttendeePreview(
                    user_id=user.id,
                    name=display,
                    avatar_url=user.avatar_url,
                )
            )
    return from_row(
        CalendarEventSummary,
        event,
        recurrence=_parse_recurrence(event),
        initiative_id=calendar.initiative_id if calendar is not None else 0,
        guild_id=guild_id if guild_id is not None else context.guild_id,
        attendee_count=len(attendees_list),
        attendee_names=names,
        attendee_previews=previews,
        property_values=_serialize_event_properties(event),
        tags=annotated_tags(event),
        can=ContentCan(edit=can_edit),
    )


def serialize_calendar_event(
    event: "CalendarEvent",
    *,
    context: ActorContext,
    user_id: Optional[int] = None,
    documents: Sequence[Related] = (),
) -> CalendarEventRead:
    summary = serialize_calendar_event_summary(event, context=context, user_id=user_id)
    return CalendarEventRead(
        **summary.model_dump(),
        attendees=_serialize_attendees(event),
        documents=_serialize_documents(documents),
    )
