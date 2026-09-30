"""Repeat rules: RFC 5545 recurrence lines, as they were picked, and a shift.

A stored repeat is one ``RRULE`` line and any ``EXDATE`` / ``RDATE`` lines:

    RRULE:FREQ=MONTHLY;BYDAY=2MO;UNTIL=20261214T225959Z
    EXDATE:20261109T083000Z

The series start is the row's own (an event's ``start_at``, a task's due date),
never a ``DTSTART`` line. The rule's days are the ones somebody picked, in their
zone; ``UNTIL``, ``EXDATE`` and ``RDATE`` are UTC. Beside it the row keeps
``recurrence_shift``, the minutes from the start's UTC time to where it was
picked: whole days (``-1440``, ``0``, ``1440``) for a rule of days, the exact
offset for a rule of hours. It is neither a zone nor its daylight-saving rules,
so every occurrence is a fixed instant, the same for every viewer.

dateutil is the one engine that turns a rule into dates: it runs the rule from
the start moved by the shift, where the picked days are, and moves every
occurrence back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from itertools import islice
from typing import Iterable, Literal

import icalendar
from dateutil.rrule import rrulestr, rruleset

from app.core.user_input_validators import resolve_zone

RecurrenceKind = Literal["task", "event"]

_WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")

#: The frequencies each kind may repeat at. Every task occurrence is a new row,
#: so tasks repeat daily at the most.
_FREQUENCIES: dict[RecurrenceKind, frozenset[str]] = {
    "task": frozenset({"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}),
    "event": frozenset({"HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"}),
}

#: The rule parts each kind may name: an event may also repeat at set hours.
_TASK_PARTS = frozenset(
    {
        "FREQ",
        "INTERVAL",
        "COUNT",
        "UNTIL",
        "WKST",
        "BYDAY",
        "BYMONTHDAY",
        "BYMONTH",
        "BYYEARDAY",
        "BYWEEKNO",
        "BYSETPOS",
    }
)
_PARTS: dict[RecurrenceKind, frozenset[str]] = {
    "task": _TASK_PARTS,
    "event": _TASK_PARTS | {"BYHOUR"},
}

# The last second of a day: the instant an all-day series' UNTIL date ends
_END_OF_DAY = time(23, 59, 59)

# Input bounds: a year of daily steps, and ten thousand occurrences, which
# saving a rule walks once to find its last start.
_MAX_INTERVAL = 366
_MAX_COUNT = 10_000


@dataclass(frozen=True)
class Recurrence:
    """One parsed repeat: its rule parts, skipped starts and extra starts."""

    rule: dict[str, list]
    exdates: tuple[date | datetime, ...] = field(default=())
    rdates: tuple[date | datetime, ...] = field(default=())

    def to_lines(self) -> str:
        """The canonical text: equal repeats are equal strings."""
        lines = [f"RRULE:{icalendar.vRecur(self.rule).to_ical().decode()}"]
        for name, values in (("EXDATE", self.exdates), ("RDATE", self.rdates)):
            days = sorted(v for v in values if not isinstance(v, datetime))
            instants = sorted(v for v in values if isinstance(v, datetime))
            if days:
                lines.append(
                    f"{name};VALUE=DATE:" + ",".join(d.strftime("%Y%m%d") for d in days)
                )
            if instants:
                lines.append(
                    f"{name}:"
                    + ",".join(
                        d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                        for d in instants
                    )
                )
        return "\n".join(lines)


def parse(text: str) -> Recurrence:
    """Read recurrence lines. Raises ``ValueError`` for anything that is not one
    ``RRULE`` with optional ``EXDATE`` / ``RDATE`` lines."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        raise ValueError("A repeat needs an RRULE line.")
    if ":" not in lines[0]:
        # A bare rule value is accepted as its RRULE line.
        lines = [f"RRULE:{lines[0]}", *lines[1:]]
    try:
        component = icalendar.Event.from_ical(
            "BEGIN:VEVENT\r\n" + "\r\n".join(lines) + "\r\nEND:VEVENT\r\n"
        )
    except ValueError as exc:
        raise ValueError(f"Not a valid repeat: {exc}") from exc
    names = {name.upper() for name in component}
    if names - {"RRULE", "EXDATE", "RDATE"}:
        raise ValueError("A repeat holds only RRULE, EXDATE and RDATE lines.")
    rule = component.get("RRULE")
    if rule is None or isinstance(rule, list):
        raise ValueError("A repeat needs exactly one RRULE line.")
    return Recurrence(
        rule={key.upper(): list(values) for key, values in rule.items()},
        exdates=tuple(_dates(component.get("EXDATE"))),
        rdates=tuple(_dates(component.get("RDATE"))),
    )


def _dates(prop) -> Iterable[date | datetime]:
    for dates in prop if isinstance(prop, list) else [prop] if prop else []:
        for value in dates.dts:
            yield value.dt


def normalize(text: str, *, kind: RecurrenceKind) -> str:
    """Validate a repeat for ``kind`` and return its canonical lines."""
    recurrence = parse(text)
    rule = recurrence.rule
    freq = rule.get("FREQ", [""])[0]
    if freq not in _FREQUENCIES[kind]:
        raise ValueError(f"This repeat can't be {str(freq).lower() or 'empty'}.")
    if extra := set(rule) - _PARTS[kind]:
        raise ValueError(f"This repeat can't use {', '.join(sorted(extra))}.")
    if "COUNT" in rule and "UNTIL" in rule:
        raise ValueError("A repeat ends after a count or on a date, not both.")
    if not 1 <= rule.get("INTERVAL", [1])[0] <= _MAX_INTERVAL:
        raise ValueError(f"A repeat's interval is 1 to {_MAX_INTERVAL}.")
    if not 1 <= rule.get("COUNT", [1])[0] <= _MAX_COUNT:
        raise ValueError(f"A repeat happens 1 to {_MAX_COUNT} times.")
    for value in [*rule.get("UNTIL", []), *recurrence.exdates, *recurrence.rdates]:
        if isinstance(value, datetime) and value.utcoffset() != timedelta(0):
            raise ValueError("A repeat's dates and times are UTC.")
    # dateutil is the engine every date comes from, so it has to read the rule.
    _series(recurrence, datetime(2000, 1, 1, tzinfo=timezone.utc), 0)
    return recurrence.to_lines()


def shift_for(text: str, start: datetime, zone: tzinfo) -> int:
    """The shift of a rule picked in ``zone`` for a series starting at
    ``start``: whole days for a rule of days, the offset for a rule of hours."""
    rule = parse(text).rule
    local = start.astimezone(zone)
    if rule["FREQ"][0] == "HOURLY" or "BYHOUR" in rule:
        return int((local.utcoffset() or timedelta(0)).total_seconds() // 60)
    return (local.date() - start.astimezone(timezone.utc).date()).days * 1440


def stored(
    text: str, start: datetime | None, tz: str | None, *, kind: RecurrenceKind
) -> tuple[str, int]:
    """A written rule and its shift: picked in ``tz``, or in UTC without one."""
    rule = normalize(text, kind=kind)
    if not tz or start is None:
        return rule, 0
    return rule, shift_for(rule, start, resolve_zone(tz))


def _series(
    recurrence: Recurrence, start: datetime, shift: int, *, count: bool = True
) -> tuple[rruleset, timedelta]:
    """The dateutil set run from the start moved by ``shift``, where the picked
    days are, and the shift to move its occurrences back by."""
    offset = timedelta(minutes=shift)
    moved = (start.astimezone(timezone.utc) + offset).replace(tzinfo=None)

    def here(value: date | datetime, at: time) -> datetime:
        if isinstance(value, datetime):
            return (value.astimezone(timezone.utc) + offset).replace(tzinfo=None)
        return datetime.combine(value, at)

    parts = dict(recurrence.rule)
    if not count:
        parts.pop("COUNT", None)
    if until := parts.get("UNTIL"):
        parts["UNTIL"] = [here(until[0], _END_OF_DAY)]
    series = rruleset()
    series.rrule(rrulestr(icalendar.vRecur(parts).to_ical().decode(), dtstart=moved))
    for value in recurrence.rdates:
        series.rdate(here(value, moved.time()))
    for value in recurrence.exdates:
        series.exdate(here(value, moved.time()))
    return series, offset


def _back(value: datetime, offset: timedelta) -> datetime:
    return (value - offset).replace(tzinfo=timezone.utc)


def first(text: str, start: datetime, shift: int, n: int) -> list[datetime]:
    """The series' first ``n`` starts."""
    series, offset = _series(parse(text), start, shift)
    return [_back(value, offset) for value in islice(series, n)]


def next_start(
    text: str, start: datetime, shift: int = 0, *, count: bool = True
) -> datetime | None:
    """The first occurrence after ``start`` of a series starting there."""
    series, offset = _series(parse(text), start, shift, count=count)
    moved = (start.astimezone(timezone.utc) + offset).replace(tzinfo=None)
    following = series.after(moved, inc=False)
    return _back(following, offset) if following else None


def last_start(
    text: str, start: datetime, shift: int = 0, *, done: int = 0
) -> datetime | None:
    """No occurrence of the series starts after this, or None when it never
    ends: UNTIL itself (or a later extra date), or a COUNT series' last start.
    ``done`` is how many of a COUNT series came before ``start``: a task series
    counts its successors itself."""
    recurrence = parse(text)
    offset = timedelta(minutes=shift)
    # An extra start given as a date is at the series' time on that date.
    at = (start.astimezone(timezone.utc) + offset).time()
    extra = [
        value.astimezone(timezone.utc)
        if isinstance(value, datetime)
        else datetime.combine(value, at, timezone.utc) - offset
        for value in recurrence.rdates
    ]
    if until := recurrence.rule.get("UNTIL"):
        end = until[0]
        if not isinstance(end, datetime):
            end = datetime.combine(end, _END_OF_DAY, timezone.utc) - offset
        return max([end.astimezone(timezone.utc), *extra])
    if count := recurrence.rule.get("COUNT"):
        left = Recurrence(
            {**recurrence.rule, "COUNT": [max(count[0] - done, 1)]},
            recurrence.exdates,
            recurrence.rdates,
        )
        series, offset = _series(left, start, shift)
        return max((_back(value, offset) for value in series), default=None)
    return None


def between(
    text: str,
    start: datetime,
    shift: int,
    lower: datetime,
    upper: datetime,
    *,
    count: bool = True,
) -> list[datetime]:
    """The occurrences starting in ``[lower, upper]``."""
    series, offset = _series(parse(text), start, shift, count=count)

    def moved(value: datetime) -> datetime:
        return (value.astimezone(timezone.utc) + offset).replace(tzinfo=None)

    return [
        _back(value, offset)
        for value in series.between(moved(lower), moved(upper), inc=True)
    ]


def upcoming(text: str, start: datetime, shift: int, now: datetime) -> datetime:
    """The first occurrence starting at or after ``now``, or, once the series
    has ended, its last."""
    series, offset = _series(parse(text), start, shift)
    moved = (now.astimezone(timezone.utc) + offset).replace(tzinfo=None)
    found = series.after(moved, inc=True) or series.before(moved)
    return _back(found, offset) if found else start


def restarted(
    text: str, shift: int, old_start: datetime, new_start: datetime, tz: str | None
) -> tuple[str, int]:
    """A series whose start moved, and its shift: the days stay as picked, the
    shift is taken again in ``tz`` (kept without one), and a skipped or extra
    start keeps its picked day at the new time of day."""
    new_shift = shift_for(text, new_start, resolve_zone(tz)) if tz else shift
    repeat = parse(text)
    old = timedelta(minutes=shift)
    new = timedelta(minutes=new_shift)
    at = (new_start.astimezone(timezone.utc) + new).time()

    def move(value: date | datetime) -> date | datetime:
        if not isinstance(value, datetime):
            return value
        day = (value.astimezone(timezone.utc) + old).date()
        return datetime.combine(day, at, timezone.utc) - new

    lines = Recurrence(
        repeat.rule,
        tuple(move(value) for value in repeat.exdates),
        tuple(move(value) for value in repeat.rdates),
    ).to_lines()
    return lines, new_shift


def moved(text: str, delta: timedelta) -> str:
    """The same repeat with its end, skipped and extra dates moved by ``delta``,
    for a template whose dates move to where it is used."""
    repeat = parse(text)
    rule = dict(repeat.rule)
    if until := rule.get("UNTIL"):
        rule["UNTIL"] = [until[0] + delta]
    return Recurrence(
        rule,
        tuple(value + delta for value in repeat.exdates),
        tuple(value + delta for value in repeat.rdates),
    ).to_lines()


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

_LEGACY_POSITIONS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "last": -1}


def from_legacy(data: dict, *, zone: tzinfo, all_day: bool = False) -> str | None:
    """A repeat in the JSON shape exports carried before RRULE, as the rule its
    days were picked in (``zone``). None when it names no frequency."""
    freq = str(data.get("frequency") or "").upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return None

    def code(day: object) -> str:
        return str(day)[:2].upper()  # "monday" and the older "MO" alike

    rule: dict[str, list] = {"FREQ": [freq]}
    if (interval := int(data.get("interval") or 1)) > 1:
        rule["INTERVAL"] = [interval]
    if freq == "WEEKLY" and data.get("weekdays"):
        rule["BYDAY"] = [code(d) for d in data["weekdays"] if code(d) in _WEEKDAYS]
    if freq in ("MONTHLY", "YEARLY"):
        if data.get("monthly_mode") == "weekday" and data.get("weekday"):
            position = _LEGACY_POSITIONS.get(data.get("weekday_position") or "first", 1)
            rule["BYDAY"] = [f"{position}{code(data['weekday'])}"]
        elif day := data.get("day_of_month"):
            # A day a short month lacks fell on that month's last day.
            rule["BYMONTHDAY"] = [day] if day <= 28 else list(range(28, day + 1))
            if day > 28:
                rule["BYSETPOS"] = [-1]
        if freq == "YEARLY" and data.get("month"):
            rule["BYMONTH"] = [int(data["month"])]
    if data.get("ends") == "after_occurrences" and data.get("end_after_occurrences"):
        rule["COUNT"] = [int(data["end_after_occurrences"])]
    elif data.get("ends") == "on_date" and data.get("end_date"):
        # The last day as the form showed it: the date the value is written with.
        last = datetime.fromisoformat(str(data["end_date"])).date()
        rule["UNTIL"] = [
            last
            if all_day
            else datetime.combine(last, _END_OF_DAY, zone).astimezone(timezone.utc)
        ]
    return Recurrence(rule).to_lines()


def imported(
    value: str | dict | None,
    *,
    kind: RecurrenceKind,
    start: datetime | None,
    tz: str | None,
    shift: int = 0,
    all_day: bool = False,
) -> tuple[str | None, int]:
    """A repeat read from an import and its shift: a rule string comes with
    its ``shift``, and the JSON shape exports carried before RRULE was picked in
    a zone the export doesn't name, which ``tz`` (the importer's) stands in
    for. A repeat that doesn't hold up imports as none."""
    try:
        if isinstance(value, dict):
            zone = resolve_zone(None if all_day else tz)
            legacy = from_legacy(value, zone=zone, all_day=all_day)
            if legacy is None:
                return None, 0
            return stored(legacy, start, None if all_day else tz, kind=kind)
        return (normalize(value, kind=kind), shift) if value else (None, 0)
    except (ValueError, TypeError):
        return None, 0
