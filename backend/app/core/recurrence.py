"""Repeat rules: RFC 5545 recurrence lines, stored in UTC terms.

A stored repeat is one ``RRULE`` line and any ``EXDATE`` / ``RDATE`` lines:

    RRULE:FREQ=MONTHLY;BYDAY=2MO;UNTIL=20261214T225959Z
    EXDATE:20261109T083000Z

The series start is the row's own (an event's ``start_at``, a task's due date),
never a ``DTSTART`` line. The rule's weekdays, month days and months are those
of the start's UTC date, and ``UNTIL``, ``EXDATE`` and ``RDATE`` are UTC, so the
stored rule means the same instants to every viewer.

People pick days in their own zone: :func:`to_utc_terms` turns those picks into
the stored rule, and :func:`to_local_terms` is the way back for an editor.
dateutil is the one engine that turns a rule into dates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
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

# Each month's length in a leap year
_LONGEST = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

# The last second of a day: the instant an all-day series' UNTIL date ends
_END_OF_DAY = time(23, 59, 59)

# Input bounds: a year of daily steps, and ten thousand occurrences, which
# saving a rule walks once to find its last start.
_MAX_INTERVAL = 366
_MAX_COUNT = 10_000

# How many occurrences the conversion check compares
_CHECKED_OCCURRENCES = 60


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
    ruleset(recurrence, datetime(2000, 1, 1, tzinfo=timezone.utc))
    return recurrence.to_lines()


def ruleset(recurrence: Recurrence, start: datetime, *, count: bool = True) -> rruleset:
    """The dateutil set for a series starting at ``start``. ``count=False``
    leaves COUNT out, for a task series whose own counter decides its end."""
    start = start.astimezone(timezone.utc)
    parts = {key: values for key, values in recurrence.rule.items()}
    if not count:
        parts.pop("COUNT", None)
    if until := parts.get("UNTIL"):
        parts["UNTIL"] = [_instant(until[0], _END_OF_DAY)]
    series = rruleset()
    series.rrule(rrulestr(icalendar.vRecur(parts).to_ical().decode(), dtstart=start))
    for value in recurrence.rdates:
        series.rdate(_instant(value, start.timetz()))
    for value in recurrence.exdates:
        series.exdate(_instant(value, start.timetz()))
    return series


def _instant(value: date | datetime, at: time) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return datetime.combine(value, at.replace(tzinfo=None), timezone.utc)


def last_start(text: str, start: datetime) -> datetime | None:
    """No occurrence of the series starts after this, or None when it never
    ends. For an UNTIL rule it is UNTIL itself (or a later extra date)."""
    recurrence = parse(text)
    extra = [_instant(value, start.timetz()) for value in recurrence.rdates]
    if until := recurrence.rule.get("UNTIL"):
        return max([_instant(until[0], _END_OF_DAY), *extra])
    if "COUNT" in recurrence.rule:
        return max(ruleset(recurrence, start), default=start.astimezone(timezone.utc))
    return None


def next_start(text: str, start: datetime, *, count: bool = True) -> datetime | None:
    """The first occurrence after ``start`` of a series starting there."""
    start = start.astimezone(timezone.utc)
    return ruleset(parse(text), start, count=count).after(start, inc=False)


def stored(
    text: str, start: datetime | None, tz: str | None, *, kind: RecurrenceKind
) -> str:
    """The rule to store for one written with its days picked in ``tz``: in UTC
    terms from ``start``. A rule written without a zone is already stored as
    it is."""
    if not tz or start is None:
        return text
    return normalize(to_utc_terms(text, start, resolve_zone(tz)), kind=kind)


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


def between(
    text: str, start: datetime, lower: datetime, upper: datetime
) -> list[datetime]:
    """The occurrences starting in ``[lower, upper]``."""
    return ruleset(parse(text), start).between(
        lower.astimezone(timezone.utc), upper.astimezone(timezone.utc), inc=True
    )


# ---------------------------------------------------------------------------
# Local picks <-> UTC terms
# ---------------------------------------------------------------------------


def to_utc_terms(text: str, start: datetime, zone: tzinfo) -> str:
    """The stored form of a rule whose days were picked in ``zone``."""
    return _shift(text, start, zone, to_utc=True)


def to_local_terms(text: str, start: datetime, zone: tzinfo) -> str:
    """A stored rule read back in ``zone``, as its days were picked there."""
    return _shift(text, start, zone, to_utc=False)


def is_exact(local_text: str, utc_text: str, start: datetime, zone: tzinfo) -> bool:
    """Whether the stored rule starts exactly when the picked one does.

    Both run at the start's own offset, so a daylight-saving change (which UTC
    terms deliberately don't follow) isn't counted as a difference."""
    fixed = timezone(start.astimezone(zone).utcoffset() or timedelta(0))
    local = rrulestr(
        f"RRULE:{icalendar.vRecur(_without_until(parse(local_text).rule)).to_ical().decode()}",
        dtstart=start.astimezone(fixed).replace(tzinfo=None),
    )
    stored = rrulestr(
        f"RRULE:{icalendar.vRecur(_without_until(parse(utc_text).rule)).to_ical().decode()}",
        dtstart=start.astimezone(timezone.utc).replace(tzinfo=None),
    )
    offset = fixed.utcoffset(None)
    picked = [value for _, value in zip(range(_CHECKED_OCCURRENCES), local)]
    kept = [value + offset for _, value in zip(range(_CHECKED_OCCURRENCES), stored)]
    return picked == kept


def _without_until(rule: dict[str, list]) -> dict[str, list]:
    # Both sides are compared on their first occurrences, naive, so the end
    # (a UTC instant on both) stays out of it.
    return {key: values for key, values in rule.items() if key != "UNTIL"}


def _shift(text: str, start: datetime, zone: tzinfo, *, to_utc: bool) -> str:
    recurrence = parse(text)
    local = start.astimezone(zone)
    utc = start.astimezone(timezone.utc)
    days = (utc.date() - local.date()).days
    offset = local.utcoffset() or timedelta(0)
    if not to_utc:
        days, offset = -days, -offset
    minutes = -int(offset.total_seconds() // 60)
    shifted = _shift_rule(recurrence.rule, days, minutes)
    candidates = [shifted]
    if days and shifted["FREQ"][0] in ("MONTHLY", "YEARLY"):
        if to_utc:
            candidates.extend(_pinned(recurrence.rule, shifted, local, days))
        else:
            # Read back, the simplest rule that means the same wins.
            candidates = [*_unpinned(shifted), shifted]
    texts = [
        Recurrence(rule, recurrence.exdates, recurrence.rdates).to_lines()
        for rule in candidates
    ]
    for candidate in texts:
        picked, stored = (text, candidate) if to_utc else (candidate, text)
        if is_exact(picked, stored, start, zone):
            return candidate
    return texts[0]


def _pinned(
    rule: dict[str, list], shifted: dict[str, list], local: datetime, days: int
) -> list[dict[str, list]]:
    """The shifted rule pinned to the days of the month, and the months, that
    the picked rule falls on: once counting days from the month's start and
    once from its end. Where a plain shift crossed a month's end, one of them
    can say exactly the same again: the last work day is always one of a
    month's last three days, the 31st exists in seven months, and June 30 is a
    last day whose next day is in July."""
    series = rrulestr(
        f"RRULE:{icalendar.vRecur(_without_until(rule)).to_ical().decode()}",
        dtstart=local.replace(tzinfo=None),
    )
    fallen = [value for _, value in zip(range(400), series)]
    months = {value.month for value in fallen}
    pins = []
    for monthdays in (
        {value.day for value in fallen},
        {value.day - _month_length(value) - 1 for value in fallen},
    ):
        pinned = {
            **shifted,
            "BYMONTHDAY": sorted(
                {_move_monthday(day, days) for day in monthdays}, key=_day_order
            ),
        }
        crossing = {_crosses_month(day, days) for day in monthdays}
        if len(crossing) == 1 and (len(months) < 12 or "BYMONTH" in rule):
            # The days all moved into the month before or after, or none did.
            step = days if crossing == {True} else 0
            pinned["BYMONTH"] = sorted((m - 1 + step) % 12 + 1 for m in months)
        pins.append(pinned)
    return pins


def _unpinned(rule: dict[str, list]) -> list[dict[str, list]]:
    """Simpler readings of a rule read back from UTC terms, simplest first: a
    pin dropped, or the last day of the seven long months read as the 31st."""
    readings = []
    lengths = {_LONGEST[month - 1] for month in rule.get("BYMONTH", [1])}
    if (
        rule.get("BYMONTHDAY") == [-1]
        and len(lengths) == 1
        and 2 not in rule.get("BYMONTH", [])
    ):
        # The last day of months that all have 31 days is the 31st; of April
        # and June, the 30th.
        readings.append(
            {
                k: v
                for k, v in rule.items()
                if k != "BYMONTH" or rule["FREQ"][0] != "MONTHLY"
            }
            | {"BYMONTHDAY": [lengths.pop()]}
        )
    for dropped in (("BYMONTHDAY", "BYMONTH"), ("BYMONTH",), ("BYMONTHDAY",)):
        if (
            any(part in rule for part in dropped)
            and "BYDAY" in rule
            and (rule["FREQ"][0] == "MONTHLY" or "BYMONTH" not in dropped)
        ):
            readings.append({k: v for k, v in rule.items() if k not in dropped})
    if rule["FREQ"][0] == "MONTHLY" and "BYMONTH" in rule:
        readings.append({k: v for k, v in rule.items() if k != "BYMONTH"})
    return readings


def _month_length(value: datetime) -> int:
    following = (value.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (following - timedelta(days=1)).day


def _shift_rule(rule: dict[str, list], days: int, minutes: int) -> dict[str, list]:
    """Move a rule's day parts by ``days`` (-1, 0 or 1) and its hours by
    ``minutes``. Where no rule says exactly the same, this is the nearest one;
    :func:`is_exact` tells the two apart."""
    shifted = {key: list(values) for key, values in rule.items()}
    if "BYHOUR" in shifted:
        shifted["BYHOUR"] = sorted(
            {((hour * 60 + minutes) // 60) % 24 for hour in shifted["BYHOUR"]}
        )
    if days == 0:
        return shifted
    weekly = shifted["FREQ"][0] == "WEEKLY" and int(shifted.get("INTERVAL", [1])[0]) > 1
    if weekly or "BYWEEKNO" in shifted:
        # Weeks start a day earlier or later too, so a day that moved past the
        # week's start stays in its week.
        start = str(shifted.get("WKST", ["MO"])[0])
        shifted["WKST"] = [_WEEKDAYS[(_WEEKDAYS.index(start) + days) % 7]]
        if shifted["WKST"] == ["MO"]:
            del shifted["WKST"]

    weekdays, ordinal = _split_byday(shifted.get("BYDAY", []))
    monthdays = [int(day) for day in shifted.get("BYMONTHDAY", [])]
    if ordinal is not None and not monthdays:
        # The nth weekday is that weekday on one stretch of the month.
        monthdays = _window(ordinal)
        ordinal = None
    if weekdays:
        shifted["BYDAY"] = [
            _WEEKDAYS[(_WEEKDAYS.index(d) + days) % 7] for d in weekdays
        ]
        if ordinal is not None:
            shifted["BYDAY"] = [f"{ordinal}{shifted['BYDAY'][0]}"]
    if monthdays:
        moved = sorted({_move_monthday(day, days) for day in monthdays}, key=_day_order)
        if (
            len(shifted.get("BYDAY", [])) == 1
            and (window := _ordinal_of(moved)) is not None
        ):
            shifted["BYDAY"] = [f"{window}{shifted['BYDAY'][0]}"]
            shifted.pop("BYMONTHDAY", None)
        else:
            shifted["BYMONTHDAY"] = moved
        if "BYMONTH" in shifted and all(_crosses_month(day, days) for day in monthdays):
            shifted["BYMONTH"] = sorted(
                (month - 1 + days) % 12 + 1 for month in shifted["BYMONTH"]
            )
    if "BYYEARDAY" in shifted:
        shifted["BYYEARDAY"] = sorted(
            {_move_yearday(day, days) for day in shifted["BYYEARDAY"]}
        )
    return shifted


def _split_byday(values: list) -> tuple[list[str], int | None]:
    """A BYDAY list as its weekday codes, plus the ordinal when the rule is one
    ordinal weekday ("2MO")."""
    codes = [str(value).upper() for value in values]
    if len(codes) == 1 and len(codes[0]) > 2:
        return [codes[0][-2:]], int(codes[0][:-2])
    return codes, None


def _move_monthday(day: int, days: int) -> int:
    """Day ``day`` of a month moved by ``days``: the 1st less a day is the last
    day of the month before, and the last day plus one is the 1st after."""
    moved = day + days
    if day > 0 and moved == 0:
        return -1
    if day < 0 and moved == 0:
        return 1
    if moved > 31:
        return 1
    if moved < -31:
        return -31
    return moved


def _crosses_month(day: int, days: int) -> bool:
    return (day == 1 and days < 0) or (day in (-1, 31) and days > 0)


def _move_yearday(day: int, days: int) -> int:
    moved = day + days
    if day > 0 and moved == 0:
        return -1
    if day < 0 and moved == 0:
        return 1
    return max(-366, min(366, moved))


def _day_order(day: int) -> tuple[int, int]:
    return (0, day) if day > 0 else (1, day)


def _window(ordinal: int) -> list[int]:
    """The days of the month the nth weekday can fall on: 1–7 for the first,
    29–31 for the fifth, -7 to -1 for the last."""
    if ordinal > 0:
        return list(range(7 * (ordinal - 1) + 1, min(7 * ordinal, 31) + 1))
    return list(range(max(7 * ordinal, -31), 7 * (ordinal + 1)))


def _ordinal_of(monthdays: list[int]) -> int | None:
    """The ordinal a stretch of month days stands for (see :func:`_window`)."""
    for ordinal in (1, 2, 3, 4, 5, -1, -2, -3, -4, -5):
        if monthdays == _window(ordinal):
            return ordinal
    return None


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

_LEGACY_POSITIONS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "last": -1}


def from_legacy(data: dict, *, all_day: bool = False) -> str | None:
    """A repeat in the JSON shape exports carried before RRULE, as rule lines in
    the terms its days were picked in. None when it names no frequency."""
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
        rule["UNTIL"] = [last if all_day else _instant(last, _END_OF_DAY)]
    return Recurrence(rule).to_lines()


def imported(
    value: str | dict | None, *, kind: RecurrenceKind, all_day: bool = False
) -> str | None:
    """A repeat read from an import: a rule string, or the JSON shape exports
    carried before RRULE. A repeat that doesn't hold up imports as none."""
    try:
        if isinstance(value, dict):
            value = from_legacy(value, all_day=all_day)
        return normalize(value, kind=kind) if value else None
    except (ValueError, TypeError):
        return None
