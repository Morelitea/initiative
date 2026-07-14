"""iCal (.ics) import/export service.

Handles conversion between CalendarEvent models and iCalendar format.
"""

import json
import logging
from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

import icalendar

from app.models.tenant.calendar_event import CalendarEvent
from app.schemas.tenant.calendar_event import EventRecurrence
from app.schemas.tenant.ical import ICalEventPreview, ICalParseResult

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

# RSVP status mapping: app -> iCal PARTSTAT
_RSVP_TO_PARTSTAT = {
    "pending": "NEEDS-ACTION",
    "accepted": "ACCEPTED",
    "declined": "DECLINED",
    "tentative": "TENTATIVE",
}


# ---------------------------------------------------------------------------
# Export: CalendarEvent -> iCal
# ---------------------------------------------------------------------------


def _recurrence_to_rrule(recurrence: Optional[dict]) -> Optional[dict]:
    """Convert a parsed recurrence dict (EventRecurrence shape) to an RRULE
    dict for icalendar."""
    if not recurrence:
        return None
    try:
        rec = EventRecurrence(**recurrence)
    except Exception:
        return None

    rule: dict = {"FREQ": [rec.frequency.upper()]}

    if rec.interval and rec.interval > 1:
        rule["INTERVAL"] = [rec.interval]

    if rec.weekdays:
        rule["BYDAY"] = rec.weekdays

    if rec.monthly_mode == "weekday" and rec.weekday_position and rec.weekday:
        pos = _POSITION_MAP.get(rec.weekday_position)
        if pos is not None:
            rule["BYDAY"] = [f"{pos}{rec.weekday.upper()}"]

    if rec.monthly_mode == "day_of_month" and rec.day_of_month:
        rule["BYMONTHDAY"] = [rec.day_of_month]

    if rec.month:
        rule["BYMONTH"] = [rec.month]

    if rec.ends == "on_date" and rec.end_date:
        if isinstance(rec.end_date, datetime):
            rule["UNTIL"] = [rec.end_date.astimezone(timezone.utc)]
        else:
            rule["UNTIL"] = [
                datetime(
                    rec.end_date.year,
                    rec.end_date.month,
                    rec.end_date.day,
                    23,
                    59,
                    59,
                    tzinfo=timezone.utc,
                )
            ]

    if rec.ends == "after_occurrences" and rec.end_after_occurrences:
        rule["COUNT"] = [rec.end_after_occurrences]

    return rule


def event_export_dict(event: CalendarEvent) -> dict:
    """One event's JSON-safe export record — the single intermediate both the
    ics renderer and the json envelope consume. Must stay JSON-serializable:
    ``RenderItem.data`` crosses the export engine's job boundary (persisted
    selectors are replayed by the worker), so no models or datetimes here.

    Attendees ride as display name + email + RSVP (informational — user ids
    are guild-local, an import can't rebind them); tags by name; linked
    documents by title."""
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
        "title": event.title,
        "description": event.description,
        "location": event.location,
        "start_at": event.start_at.isoformat(),
        "end_at": event.end_at.isoformat(),
        "all_day": bool(event.all_day),
        "color": event.color,
        "recurrence": recurrence,
        "created_at": event.created_at.isoformat(),
        "updated_at": event.updated_at.isoformat(),
        "attendees": [
            {
                "name": attendee.user.full_name or None,
                "email": attendee.user.email or None,
                "rsvp": attendee.rsvp_status.value
                if hasattr(attendee.rsvp_status, "value")
                else str(attendee.rsvp_status),
            }
            for attendee in event.attendees or []
            if attendee.user is not None
        ],
        "tags": sorted(
            link.tag.name for link in event.tag_links or [] if link.tag is not None
        ),
        "documents": sorted(
            link.document.title
            for link in event.document_links or []
            if link.document is not None
        ),
        "properties": [
            _property_export_dict(pv)
            for pv in event.property_values or []
            if pv.property_definition is not None
        ],
    }


def _property_export_dict(pv) -> dict:
    """A custom property value, flat and by NAME (never id) — the same
    type→field encoding the project envelope uses (see
    ``project_export._serialize_property_value``), so a future import reads
    both with one rule set: text/url/select → value_text; number →
    value_number; checkbox → value_boolean; date/datetime → value_text (ISO
    8601); multi_select → value_json; user_reference → value_email."""
    prop = pv.property_definition
    prop_type = prop.type.value if hasattr(prop.type, "value") else str(prop.type)
    record: dict = {"property_name": prop.name, "property_type": prop_type}
    if prop_type in ("text", "url", "select"):
        record["value_text"] = pv.value_text
    elif prop_type == "number":
        record["value_number"] = (
            float(pv.value_number) if pv.value_number is not None else None
        )
    elif prop_type == "checkbox":
        record["value_boolean"] = pv.value_boolean
    elif prop_type == "date":
        record["value_text"] = pv.value_date.isoformat() if pv.value_date else None
    elif prop_type == "datetime":
        record["value_text"] = (
            pv.value_datetime.isoformat() if pv.value_datetime else None
        )
    elif prop_type == "multi_select":
        record["value_json"] = pv.value_json
    elif prop_type == "user_reference":
        record["value_email"] = pv.value_user.email if pv.value_user else None
    return record


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def ical_from_export_dicts(events: List[dict]) -> bytes:
    """Serialize event export dicts (``event_export_dict`` shape) to iCal
    bytes — the render half of the split, callable from the export engine's
    worker replay where only JSON survives."""
    cal = icalendar.Calendar()
    cal.add("prodid", "-//Initiative//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")

    for event in events:
        vevent = icalendar.Event()
        vevent.add("uid", f"event-{event.get('id')}@initiative")
        vevent.add("summary", event.get("title") or "")

        start_at = _dt(event["start_at"])
        end_at = _dt(event["end_at"])
        if event.get("all_day"):
            vevent.add("dtstart", start_at.date())
            vevent.add("dtend", end_at.date())
        else:
            vevent.add("dtstart", start_at.astimezone(timezone.utc))
            vevent.add("dtend", end_at.astimezone(timezone.utc))

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

        rrule = _recurrence_to_rrule(event.get("recurrence"))
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

    return cal.to_ical()


def events_to_ical(events: List[CalendarEvent]) -> bytes:
    """Serialize a list of CalendarEvent models to iCal bytes."""
    return ical_from_export_dicts([event_export_dict(event) for event in events])


# ---------------------------------------------------------------------------
# Import: iCal -> parsed data
# ---------------------------------------------------------------------------


def _rrule_to_recurrence(rrule) -> Optional[dict]:
    """Convert an iCal RRULE to our EventRecurrence JSON dict. Best-effort."""
    try:
        freq = rrule.get("FREQ", [None])[0]
        if not freq:
            return None
        freq_lower = freq.lower() if isinstance(freq, str) else freq

        rec: dict = {"frequency": freq_lower}

        interval = rrule.get("INTERVAL", [1])
        if interval and interval[0] > 1:
            rec["interval"] = interval[0]

        byday = rrule.get("BYDAY", [])
        if byday:
            days = []
            for d in byday:
                day_str = str(d)
                if len(day_str) > 2:
                    pos_str = day_str[:-2]
                    weekday = day_str[-2:]
                    try:
                        pos_num = int(pos_str)
                        pos_name = _POSITION_REVERSE.get(pos_num)
                        if pos_name:
                            rec["monthly_mode"] = "weekday"
                            rec["weekday_position"] = pos_name
                            rec["weekday"] = weekday.upper()
                    except ValueError:
                        days.append(day_str.upper())
                else:
                    days.append(day_str.upper())
            if days:
                rec["weekdays"] = days

        bymonthday = rrule.get("BYMONTHDAY", [])
        if bymonthday:
            rec["monthly_mode"] = "day_of_month"
            rec["day_of_month"] = bymonthday[0]

        bymonth = rrule.get("BYMONTH", [])
        if bymonth:
            rec["month"] = bymonth[0]

        count = rrule.get("COUNT", [])
        if count:
            rec["ends"] = "after_occurrences"
            rec["end_after_occurrences"] = count[0]

        until = rrule.get("UNTIL", [])
        if until:
            rec["ends"] = "on_date"
            end_val = until[0]
            if isinstance(end_val, datetime):
                rec["end_date"] = end_val.isoformat()
            elif isinstance(end_val, date):
                rec["end_date"] = datetime(
                    end_val.year,
                    end_val.month,
                    end_val.day,
                    tzinfo=timezone.utc,
                ).isoformat()

        if "ends" not in rec:
            rec["ends"] = "never"

        return rec
    except Exception:
        logger.warning("Failed to convert RRULE to recurrence", exc_info=True)
        return None


def _extract_vevent(component) -> Optional[dict]:
    """Extract event data from a VEVENT component."""
    summary = str(component.get("summary", "Untitled Event"))
    dtstart = component.get("dtstart")
    dtend = component.get("dtend")

    if not dtstart:
        return None

    start_val = dtstart.dt
    all_day = isinstance(start_val, date) and not isinstance(start_val, datetime)

    if all_day:
        start_dt = datetime(
            start_val.year,
            start_val.month,
            start_val.day,
            tzinfo=timezone.utc,
        )
        if dtend:
            end_val = dtend.dt
            end_dt = datetime(
                end_val.year,
                end_val.month,
                end_val.day,
                tzinfo=timezone.utc,
            )
        else:
            end_dt = start_dt
    else:
        start_dt = (
            start_val if start_val.tzinfo else start_val.replace(tzinfo=timezone.utc)
        )
        if dtend:
            end_val = dtend.dt
            end_dt = end_val if end_val.tzinfo else end_val.replace(tzinfo=timezone.utc)
        else:
            end_dt = start_dt

    rrule = component.get("rrule")
    recurrence = _rrule_to_recurrence(rrule) if rrule else None

    return {
        "summary": summary,
        "description": str(component.get("description", "")) or None,
        "location": str(component.get("location", "")) or None,
        "start_at": start_dt,
        "end_at": end_dt,
        "all_day": all_day,
        "recurrence": recurrence,
    }


def parse_ical(content: str) -> ICalParseResult:
    """Parse an .ics string and return a preview of found events."""
    cal = icalendar.Calendar.from_ical(content)
    events: List[ICalEventPreview] = []
    has_recurring = False

    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        data = _extract_vevent(component)
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
    initiative_id: int,
    guild_id: int,
    created_by_id: int,
) -> Tuple[List[CalendarEvent], List[str], int]:
    """Parse .ics content and build CalendarEvent model instances.

    Returns (events, errors, skipped_count). Does NOT persist — caller handles that.
    """
    cal = icalendar.Calendar.from_ical(content)
    events: List[CalendarEvent] = []
    errors: List[str] = []
    skipped = 0

    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        try:
            data = _extract_vevent(component)
            if not data:
                errors.append("Skipped event with no start date")
                skipped += 1
                continue

            event = CalendarEvent(
                guild_id=guild_id,
                initiative_id=initiative_id,
                title=data["summary"][:255],
                description=data["description"],
                location=data["location"][:500] if data["location"] else None,
                start_at=data["start_at"],
                end_at=data["end_at"],
                all_day=data["all_day"],
                recurrence=json.dumps(data["recurrence"])
                if data["recurrence"]
                else None,
                created_by_id=created_by_id,
            )
            events.append(event)
        except Exception as exc:
            summary = str(component.get("summary", "Unknown"))
            errors.append(f"Failed to import '{summary}': {exc}")
            skipped += 1

    return events, errors, skipped
