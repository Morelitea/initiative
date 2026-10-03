from __future__ import annotations

from datetime import datetime
from typing import Any, List, Mapping, Optional, Sequence, TYPE_CHECKING

from pydantic import ConfigDict, Field, PrivateAttr, field_serializer, model_validator

from app.core import recurrence
from app.core.identity_boundary import GuildId, PersonId, names_withheld
from app.core.relationships import Related
from app.schemas.base import SanitizedBaseModel, TitleStr
from app.schemas.recurrence import EventRule, OccurrenceScope

from app.models.tenant.calendar_event import RSVPStatus
from app.schemas.tenant.property import (
    PropertiesOnCreate,
    PropertiesOnUpdate,
    PropertySummary,
    annotated_properties,
)
from app.schemas.tenant.archive import ContentCan
from app.schemas.tenant.tag import TagSummary, annotated_tags
from app.schemas.tenant.tool import from_row
from app.schemas.platform.user import AppPerson, PersonShape, UserPublic
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
    #: An answer is for one event: on a repeating one, the occurrence it is
    #: for, by its start in the series. An occurrence with a row of its own is
    #: answered on that row.
    occurrence: Optional[datetime] = None


class OccurrenceRequest(SanitizedBaseModel):
    #: The occurrence, by its start in the series, or the extra start to add.
    start: datetime


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
    recurrence: Optional[str] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "CalendarEventBase":
        if self.end_at < self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class CalendarEventCreate(CalendarEventBase, PropertiesOnCreate):
    title: TitleStr = Field(..., min_length=1, max_length=255)
    calendar_id: int
    recurrence: Optional[EventRule] = None
    #: The zone ``recurrence``'s days were picked in, and ``recurrence_shift``
    #: is taken from it; an all-day event's days are UTC dates already.
    #: Omitted, the rule's days are UTC days.
    tz: Optional[str] = Field(default=None, max_length=64)
    attendee_ids: Optional[List[PersonId]] = None
    tag_ids: Optional[List[int]] = None
    document_ids: Optional[List[int]] = None


class CalendarEventUpdate(PropertiesOnUpdate):
    title: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=500)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    all_day: Optional[bool] = None
    recurrence: Optional[EventRule] = None
    #: The zone ``recurrence``'s days were picked in, and ``recurrence_shift``
    #: is taken from it; an all-day event's days are UTC dates already.
    #: Omitted, the rule's days are UTC days.
    tz: Optional[str] = Field(default=None, max_length=64)
    # Move the event to another calendar (requires write on both calendars).
    calendar_id: Optional[int] = None
    #: Replaces every tag on the event; omitted leaves them as they are.
    tag_ids: Optional[List[int]] = Field(default=None, max_length=100)
    #: For a repeating event: change one occurrence, it and every later one
    #: (a new series from there), or all of them. Omitted, the event's own row:
    #: the series, or an occurrence opened on its own.
    scope: Optional[OccurrenceScope] = None
    #: The occurrence, by its start in the series. Its new times for "all"
    #: move every occurrence by as much.
    occurrence: Optional[datetime] = None


class CalendarEventAttendeePreview(PersonShape):
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
    avatar_url: Optional[str] = None
    #: The person ``name`` was drawn from, for an installed app's response.
    _person: Optional[AppPerson] = PrivateAttr(default=None)

    @classmethod
    def of(cls, user: Any) -> "CalendarEventAttendeePreview":
        """The preview of ``user``, an attendee's person row."""
        preview = cls(
            user_id=user.id, name=display_name(user), avatar_url=user.avatar_url
        )
        preview._person = AppPerson.model_validate(user, from_attributes=True)
        return preview

    def app_person(self) -> AppPerson:
        return self._person or AppPerson(id=self.user_id)


class CalendarEventSummary(CalendarEventBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    # See ``app.core.recurrence``: a rule's days are where the start moved by
    # this many minutes lands.
    recurrence_shift: int = 0
    #: The occurrence of a repeating event this is, by the start it has in the
    #: series; None for an event that does not repeat, and for the series
    #: itself.
    original_start: Optional[datetime] = None
    #: The series an occurrence with a row of its own belongs to.
    series_id: Optional[int] = None
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
    properties: List[PropertySummary] = Field(default_factory=list)
    tags: List[TagSummary] = Field(default_factory=list)
    #: What the caller may do to this event — its calendar's edit, since events
    #: hold no grants of their own.
    can: ContentCan = Field(default_factory=ContentCan)
    created_at: datetime
    updated_at: datetime

    @field_serializer("attendee_names")
    def _attendee_names_out(self, names: List[str]) -> List[str]:
        """An installed app reads people's names under ``members:read`` only."""
        return [] if names_withheld() else names


class CalendarEventRead(CalendarEventSummary):
    attendees: List[CalendarEventAttendeeRead] = Field(default_factory=list)
    documents: List[CalendarEventDocumentRead] = Field(default_factory=list)
    #: What an occurrence changed; the rest follows its series.
    overridden_fields: List[str] = Field(default_factory=list)
    #: A series' skipped starts and extra starts.
    skipped_starts: List[datetime] = Field(default_factory=list)
    extra_starts: List[datetime] = Field(default_factory=list)


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


def _serialize_attendees(
    event: "CalendarEvent", answers: Mapping[int, RSVPStatus]
) -> List[CalendarEventAttendeeRead]:
    attendees_list = getattr(event, "attendees", None) or []
    result: List[CalendarEventAttendeeRead] = []
    for att in attendees_list:
        user = getattr(att, "user", None)
        result.append(
            CalendarEventAttendeeRead(
                user_id=att.user_id,
                user=UserPublic.model_validate(user) if user else None,
                rsvp_status=answers.get(att.user_id, att.rsvp_status),
                created_at=att.created_at,
            )
        )
    return result


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
            preview = CalendarEventAttendeePreview.of(user)
            names.append(preview.name)
            previews.append(preview)
    return from_row(
        CalendarEventSummary,
        event,
        initiative_id=calendar.initiative_id if calendar is not None else 0,
        guild_id=guild_id if guild_id is not None else context.guild_id,
        attendee_count=len(attendees_list),
        attendee_names=names,
        attendee_previews=previews,
        properties=annotated_properties(event),
        tags=annotated_tags(event),
        can=ContentCan(edit=can_edit),
    )


def serialize_calendar_event(
    event: "CalendarEvent",
    *,
    context: ActorContext,
    user_id: Optional[int] = None,
    documents: Sequence[Related] = (),
    answers: Mapping[int, RSVPStatus] | None = None,
) -> CalendarEventRead:
    """``answers`` are one occurrence's, shown in place of the series'."""
    summary = serialize_calendar_event_summary(event, context=context, user_id=user_id)
    skipped, extra = (
        recurrence.exception_starts(
            event.recurrence, event.start_at, event.recurrence_shift
        )
        if event.recurrence
        else ([], [])
    )
    return CalendarEventRead(
        **dict(summary),
        attendees=_serialize_attendees(event, answers or {}),
        documents=_serialize_documents(documents),
        overridden_fields=list(event.overridden_fields or []),
        skipped_starts=skipped,
        extra_starts=extra,
    )
