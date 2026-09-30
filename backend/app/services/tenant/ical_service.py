"""iCal (.ics) import/export service.

Handles conversion between CalendarEvent models and iCalendar format.
"""

import json
import logging
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import List, Optional, Sequence, Tuple

import icalendar
from pydantic import ValidationError

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import Related
from app.core.user_input_validators import resolve_zone
from app.models.tenant.calendar_event import CalendarEvent
from app.schemas.tenant.calendar_event import EventRecurrence
from app.schemas.tenant.ical import ICalEventPreview, ICalParseResult
from app.services.export.property_values import property_export_dict
from app.services.tenant.recurrence import WEEKDAY_NAMES
from app.core.user_display import display_name

logger = logging.getLogger(__name__)

# Weekday position mapping: app -> RRULE positional prefix
_POSITION_MAP = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "last": -1,
}
_POSITION_REVERSE = {v: k for k, v in _POSITION_MAP.items()}

# Weekday mapping: app name ("monday") <-> RRULE BYDAY code ("MO")
_WEEKDAY_BY_CODE = {name[:2].upper(): name for name in WEEKDAY_NAMES}
# Export also accepts a code, the form imports stored before they mapped it
_BYDAY_CODE = {
    **{name: code for code, name in _WEEKDAY_BY_CODE.items()},
    **{code.lower(): code for code in _WEEKDAY_BY_CODE},
}

# RSVP status mapping: app -> iCal PARTSTAT
# The RRULE parts EventRecurrence can hold
_RRULE_PARTS = {
    "FREQ",
    "INTERVAL",
    "COUNT",
    "UNTIL",
    "BYDAY",
    "BYMONTHDAY",
    "BYMONTH",
    "BYSETPOS",
    "WKST",
}

# The last second of a day: an all-day event's end, a repeat's last day
_END_OF_DAY = time(23, 59, 59)

_RSVP_TO_PARTSTAT = {
    "pending": "NEEDS-ACTION",
    "accepted": "ACCEPTED",
    "declined": "DECLINED",
    "tentative": "TENTATIVE",
}


# ---------------------------------------------------------------------------
# Export: CalendarEvent -> iCal
# ---------------------------------------------------------------------------


def _recurrence_to_rrule(
    recurrence: Optional[dict], start: datetime, all_day: bool
) -> Optional[dict]:
    """Convert a parsed recurrence dict (EventRecurrence shape) to an RRULE
    dict for icalendar, against the event's start in the export's zone. Each
    field is written only for the frequencies the recurrence engine reads it
    for, since the form keeps the others."""
    if not recurrence:
        return None
    try:
        rec = EventRecurrence(**recurrence)
    except Exception:
        return None

    rule: dict = {"FREQ": [rec.frequency.upper()]}

    if rec.interval and rec.interval > 1:
        rule["INTERVAL"] = [rec.interval]

    if rec.frequency == "weekly" and rec.weekdays:
        codes = [_BYDAY_CODE.get(day.lower()) for day in rec.weekdays]
        if codes := [code for code in codes if code]:
            rule["BYDAY"] = codes

    if rec.frequency in ("monthly", "yearly"):
        if rec.monthly_mode == "weekday" and rec.weekday_position and rec.weekday:
            pos = _POSITION_MAP.get(rec.weekday_position)
            code = _BYDAY_CODE.get(rec.weekday.lower())
            if pos is not None and code:
                rule["BYDAY"] = [f"{pos}{code}"]
        elif rec.monthly_mode == "day_of_month" and rec.day_of_month:
            rule["BYMONTHDAY"] = [rec.day_of_month]

    # A yearly BYDAY or BYMONTHDAY without BYMONTH repeats in every month;
    # the engine falls back to the start's month, so the rule names it.
    if rec.frequency == "yearly":
        rule["BYMONTH"] = [rec.month or start.month]

    if rec.ends == "on_date" and rec.end_date:
        # The last repeat falls on the day the stored value is written with,
        # the day the form shows, inclusive.
        last_day = rec.end_date.date()
        rule["UNTIL"] = [
            last_day
            if all_day
            else datetime.combine(last_day, _END_OF_DAY, start.tzinfo).astimezone(
                timezone.utc
            )
        ]

    if rec.ends == "after_occurrences" and rec.end_after_occurrences:
        rule["COUNT"] = [rec.end_after_occurrences]

    return rule


def event_export_dict(
    event: CalendarEvent, documents: "Sequence[Related]" = ()
) -> dict:
    """One event's JSON-safe export record — the single intermediate both the
    ics renderer and the json envelope consume. Must stay JSON-serializable:
    ``RenderItem.data`` crosses the export engine's job boundary (persisted
    selectors are replayed by the worker), so no models or datetimes here.

    Attendees ride as display name + email + RSVP (informational — user ids
    are guild-local, an import can't rebind them); tags by name; linked
    documents by name — handed in, because the edges live in their own table
    and a calendar export renders every event at once."""
    recurrence: Optional[dict] = None
    if event.recurrence:
        try:
            recurrence = EventRecurrence(**json.loads(event.recurrence)).model_dump(
                mode="json"
            )
        except Exception:
            recurrence = None
    return {
        "id": event.id,
        # The name this event answers to across one import. An id is guild-
        # local and means nothing on the far side; this string is what a task
        # in another envelope points at when it says which sprint it was in.
        "external_ref": f"calendar_event:{event.id}",
        "title": event.title,
        "description": event.description,
        "location": event.location,
        "start_at": event.start_at.isoformat(),
        "end_at": event.end_at.isoformat(),
        "all_day": bool(event.all_day),
        "recurrence": recurrence,
        "created_at": event.created_at.isoformat(),
        "updated_at": event.updated_at.isoformat(),
        "attendees": [
            {
                "name": display_name(attendee.user),
                # An address is never a guild's to hand out, so ATTENDEE
                # carries the participant without a reachable mailbox.
                "email": None,
                "rsvp": attendee.rsvp_status.value
                if hasattr(attendee.rsvp_status, "value")
                else str(attendee.rsvp_status),
            }
            for attendee in event.attendees or []
            if attendee.user is not None
        ],
        "tags": sorted(tag.name for tag in event.tags or []),
        "documents": sorted(
            related.entity.name for related in documents if related.entity is not None
        ),
        "properties": [
            property_export_dict(pv)
            for pv in event.property_values or []
            if pv.property_definition is not None
        ],
    }


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def ical_from_export_dicts(events: List[dict], tz: Optional[str] = None) -> bytes:
    """Serialize event export dicts (``event_export_dict`` shape) to iCal
    bytes — the render half of the split, callable from the export engine's
    worker replay where only JSON survives.

    Times are written in ``tz``, the zone the exporter plans in: the form
    picks an all-day event's days and a repeat's weekdays in that zone."""
    zone = resolve_zone(tz)
    cal = icalendar.Calendar()
    cal.add("prodid", "-//Initiative//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")

    for event in events:
        vevent = icalendar.Event()
        vevent.add("uid", f"event-{event.get('id')}@initiative")
        vevent.add("summary", event.get("title") or "")

        start_at = _dt(event["start_at"]).astimezone(zone)
        end_at = _dt(event["end_at"]).astimezone(zone)
        all_day = bool(event.get("all_day"))
        if all_day:
            # An all-day event runs to its last day's 23:59:59; DTEND is the
            # day after, exclusive.
            start_day = start_at.date()
            last_day = max((end_at - timedelta(seconds=1)).date(), start_day)
            vevent.add("dtstart", start_day)
            vevent.add("dtend", last_day + timedelta(days=1))
        else:
            vevent.add("dtstart", start_at)
            vevent.add("dtend", end_at)

        if event.get("description"):
            vevent.add("description", event["description"])
        if event.get("location"):
            vevent.add("location", event["location"])

        if event.get("created_at"):
            vevent.add("created", _dt(event["created_at"]).astimezone(timezone.utc))
        if event.get("updated_at"):
            vevent.add(
                "last-modified", _dt(event["updated_at"]).astimezone(timezone.utc)
            )

        rrule = _recurrence_to_rrule(event.get("recurrence"), start_at, all_day)
        if rrule:
            vevent.add("rrule", rrule)

        for attendee in event.get("attendees") or []:
            email = attendee.get("email")
            if not email:
                continue
            att = icalendar.vCalAddress(f"mailto:{email}")
            if attendee.get("name"):
                att.params["CN"] = icalendar.vText(attendee["name"])
            att.params["PARTSTAT"] = icalendar.vText(
                _RSVP_TO_PARTSTAT.get(attendee.get("rsvp"), "NEEDS-ACTION")
            )
            vevent.add("attendee", att, encode=0)

        cal.add_component(vevent)

    cal.add_missing_timezones()
    return cal.to_ical()


async def documents_for_events(
    session: "AsyncSession", events: List[CalendarEvent]
) -> "dict[int, list[Related]]":
    """Attached documents for many events, in two queries.

    Here rather than at each caller: the builders above are synchronous and hold
    no session, and a calendar export renders every event a calendar has.

    Keyed by event id, which is unambiguous because this reads ONE guild's
    schema. A caller walking several guilds must not merge these dicts — ids
    repeat across schemas — and should carry each list with its event instead.
    """
    from app.core.relationships import RelationshipType
    from app.core.search import SearchEntityType
    from app.models.tenant.document import Document
    from app.services.tenant import relationships

    return await relationships.related_for_many(
        session,
        SearchEntityType.calendar_event,
        [event.id for event in events if event.id is not None],
        relationship_type=RelationshipType.attached,
        other_kind=SearchEntityType.document,
        model=Document,
    )


# ---------------------------------------------------------------------------
# Import: iCal -> parsed data
# ---------------------------------------------------------------------------


def _rrule_to_recurrence(rrule, start: datetime, zone: tzinfo) -> Optional[dict]:
    """Convert an iCal RRULE to our EventRecurrence JSON dict, read in
    ``zone`` against the event's first ``start``. A rule the model cannot
    hold as written — an hourly frequency, the last day of a month, a fifth
    Monday — returns None and imports as a single event, never as a
    different schedule."""
    if set(rrule) - _RRULE_PARTS:
        return None
    freq = str(rrule.get("FREQ", [""])[0]).lower()
    byday = [str(day).upper() for day in rrule.get("BYDAY", [])]
    bymonthday = rrule.get("BYMONTHDAY", [])
    bymonth = rrule.get("BYMONTH", [])
    setpos = rrule.get("BYSETPOS", [])
    rec: dict = {"frequency": freq, "interval": rrule.get("INTERVAL", [1])[0]}

    if freq == "weekly":
        if bymonthday or bymonth or setpos:
            return None
        if any(day not in _WEEKDAY_BY_CODE for day in byday):
            return None
        if byday:
            rec["weekdays"] = [_WEEKDAY_BY_CODE[day] for day in byday]
    elif freq in ("monthly", "yearly"):
        if byday:
            # "The second Monday" is BYDAY=2MO, or BYDAY=MO;BYSETPOS=2.
            prefix = byday[0][:-2]
            if len(byday) != 1 or bymonthday or len(setpos) > 1 or (prefix and setpos):
                return None
            try:
                position = _POSITION_REVERSE.get(int(prefix or setpos[0]))
            except (ValueError, IndexError):
                return None
            weekday = _WEEKDAY_BY_CODE.get(byday[0][-2:])
            if position is None or weekday is None:
                return None
            rec["monthly_mode"] = "weekday"
            rec["weekday_position"] = position
            rec["weekday"] = weekday
        elif bymonthday:
            if len(bymonthday) != 1 or setpos:
                return None
            rec["monthly_mode"] = "day_of_month"
            rec["day_of_month"] = bymonthday[0]
        elif setpos:
            return None
        if bymonth:
            if freq == "monthly" or len(bymonth) != 1:
                return None
            rec["month"] = bymonth[0]
    elif byday or bymonthday or bymonth or setpos:
        return None

    count = rrule.get("COUNT", [])
    if count:
        rec["ends"] = "after_occurrences"
        rec["end_after_occurrences"] = count[0]

    until = rrule.get("UNTIL", [])
    if until:
        # The last repeat is the last start at or before UNTIL, stored the way
        # the form stores a picked day: its midnight, no zone.
        last = until[0]
        if isinstance(last, datetime):
            last = last.astimezone(zone) if last.tzinfo else last.replace(tzinfo=zone)
            first = start.astimezone(zone)
            last = last.date() - timedelta(days=int(first.time() > last.time()))
        rec["ends"] = "on_date"
        rec["end_date"] = datetime.combine(last, time())

    try:
        return EventRecurrence(**rec).model_dump(mode="json", exclude_none=True)
    except ValidationError:
        return None


def _extract_vevent(component, zone: tzinfo) -> Optional[dict]:
    """Extract event data from a VEVENT component. Dates and floating times
    are read in ``zone``, the importer's; an all-day event is stored the way
    the form stores one, first midnight to last 23:59:59."""
    summary = str(component.get("summary", "Untitled Event"))
    dtstart = component.get("dtstart")
    dtend = component.get("dtend")

    if not dtstart:
        return None

    start_val = dtstart.dt
    end_val = dtend.dt if dtend else start_val
    all_day = isinstance(start_val, date) and not isinstance(start_val, datetime)

    if all_day:
        if isinstance(end_val, datetime):
            end_val = end_val.date()
        # DTEND is exclusive: the last day is the one before it.
        last_day = max(end_val - timedelta(days=1), start_val)
        start_dt = datetime.combine(start_val, time(), zone)
        end_dt = datetime.combine(last_day, _END_OF_DAY, zone)
    else:
        start_dt = start_val if start_val.tzinfo else start_val.replace(tzinfo=zone)
        end_dt = end_val if end_val.tzinfo else end_val.replace(tzinfo=zone)

    rrule = component.get("rrule")
    recurrence = _rrule_to_recurrence(rrule, start_dt, zone) if rrule else None

    return {
        "summary": summary,
        "description": str(component.get("description", "")) or None,
        "location": str(component.get("location", "")) or None,
        "start_at": start_dt,
        "end_at": end_dt,
        "all_day": all_day,
        "recurrence": recurrence,
    }


def parse_ical(content: str, tz: Optional[str] = None) -> ICalParseResult:
    """Parse an .ics string and return a preview of found events."""
    zone = resolve_zone(tz)
    cal = icalendar.Calendar.from_ical(content)
    events: List[ICalEventPreview] = []
    has_recurring = False

    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        data = _extract_vevent(component, zone)
        if not data:
            continue
        has_rec = data["recurrence"] is not None
        if has_rec:
            has_recurring = True
        events.append(
            ICalEventPreview(
                summary=data["summary"],
                start_at=data["start_at"].isoformat(),
                end_at=data["end_at"].isoformat() if data["end_at"] else None,
                all_day=data["all_day"],
                has_recurrence=has_rec,
            )
        )

    return ICalParseResult(
        event_count=len(events),
        events=events,
        has_recurring=has_recurring,
    )


def build_calendar_events(
    content: str,
    calendar_id: int,
    guild_id: int,
    created_by: int,
    tz: Optional[str] = None,
) -> Tuple[List[CalendarEvent], List[str], int]:
    """Parse .ics content and build CalendarEvent model instances attached to
    the target calendar.

    Returns (events, errors, skipped_count). Does NOT persist — caller handles that.
    """
    zone = resolve_zone(tz)
    cal = icalendar.Calendar.from_ical(content)
    events: List[CalendarEvent] = []
    errors: List[str] = []
    skipped = 0

    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        try:
            data = _extract_vevent(component, zone)
            if not data:
                errors.append("Skipped event with no start date")
                skipped += 1
                continue

            event = CalendarEvent(
                calendar_id=calendar_id,
                title=data["summary"][:255],
                description=data["description"],
                location=data["location"][:500] if data["location"] else None,
                start_at=data["start_at"],
                end_at=data["end_at"],
                all_day=data["all_day"],
                recurrence=json.dumps(data["recurrence"])
                if data["recurrence"]
                else None,
                created_by=created_by,
            )
            events.append(event)
        except Exception:
            summary = str(component.get("summary", "Unknown"))
            logger.exception("iCal import could not read event %r", summary)
            errors.append(f"Failed to import '{summary}'")
            skipped += 1

    return events, errors, skipped
