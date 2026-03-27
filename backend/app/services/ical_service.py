"""iCal (.ics) import/export service.

Handles conversion between CalendarEvent models and iCalendar format.
"""

import json
import logging
from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

import icalendar

from app.models.calendar_event import CalendarEvent
from app.schemas.calendar_event import EventRecurrence
from app.schemas.ical import ICalEventPreview, ICalParseResult

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


def _recurrence_to_rrule(recurrence_json: Optional[str]) -> Optional[dict]:
    """Convert stored recurrence JSON to RRULE dict for icalendar."""
    if not recurrence_json:
        return None
    try:
        data = json.loads(recurrence_json)
        rec = EventRecurrence(**data)
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
        end_dt = rec.end_date if isinstance(rec.end_date, datetime) else rec.end_date
        if isinstance(end_dt, datetime):
            rule["UNTIL"] = [end_dt.astimezone(timezone.utc)]
        else:
            rule["UNTIL"] = [end_dt]

    if rec.ends == "after_occurrences" and rec.end_after_occurrences:
        rule["COUNT"] = [rec.end_after_occurrences]

    return rule


def events_to_ical(events: List[CalendarEvent]) -> bytes:
    """Serialize a list of CalendarEvent models to iCal bytes."""
    cal = icalendar.Calendar()
    cal.add("prodid", "-//Initiative//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")

    for event in events:
        vevent = icalendar.Event()
        vevent.add("uid", f"event-{event.id}@initiative")
        vevent.add("summary", event.title)

        if event.all_day:
            vevent.add("dtstart", event.start_at.date())
            vevent.add("dtend", event.end_at.date())
        else:
            vevent.add("dtstart", event.start_at.astimezone(timezone.utc))
            vevent.add("dtend", event.end_at.astimezone(timezone.utc))

        if event.description:
            vevent.add("description", event.description)
        if event.location:
            vevent.add("location", event.location)

        vevent.add("created", event.created_at.astimezone(timezone.utc))
        vevent.add("last-modified", event.updated_at.astimezone(timezone.utc))

        rrule = _recurrence_to_rrule(event.recurrence)
        if rrule:
            vevent.add("rrule", rrule)

        for attendee in (event.attendees or []):
            user = attendee.user
            if user and user.email:
                att = icalendar.vCalAddress(f"mailto:{user.email}")
                if user.full_name:
                    att.params["CN"] = icalendar.vText(user.full_name)
                partstat = _RSVP_TO_PARTSTAT.get(
                    attendee.rsvp_status.value if hasattr(attendee.rsvp_status, "value") else attendee.rsvp_status,
                    "NEEDS-ACTION",
                )
                att.params["PARTSTAT"] = icalendar.vText(partstat)
                vevent.add("attendee", att, encode=0)

        cal.add_component(vevent)

    return cal.to_ical()


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
                    end_val.year, end_val.month, end_val.day,
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
            start_val.year, start_val.month, start_val.day,
            tzinfo=timezone.utc,
        )
        if dtend:
            end_val = dtend.dt
            end_dt = datetime(
                end_val.year, end_val.month, end_val.day,
                tzinfo=timezone.utc,
            )
        else:
            end_dt = start_dt
    else:
        start_dt = start_val if start_val.tzinfo else start_val.replace(tzinfo=timezone.utc)
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
        events.append(ICalEventPreview(
            summary=data["summary"],
            start_at=data["start_at"].isoformat(),
            end_at=data["end_at"].isoformat() if data["end_at"] else None,
            all_day=data["all_day"],
            has_recurrence=has_rec,
        ))

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
) -> Tuple[List[CalendarEvent], List[str]]:
    """Parse .ics content and build CalendarEvent model instances.

    Returns (events, errors). Does NOT persist — the caller handles that.
    """
    cal = icalendar.Calendar.from_ical(content)
    events: List[CalendarEvent] = []
    errors: List[str] = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        try:
            data = _extract_vevent(component)
            if not data:
                errors.append("Skipped event with no start date")
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
                recurrence=json.dumps(data["recurrence"]) if data["recurrence"] else None,
                created_by_id=created_by_id,
            )
            events.append(event)
        except Exception as exc:
            summary = str(component.get("summary", "Unknown"))
            errors.append(f"Failed to import '{summary}': {exc}")

    return events, errors
