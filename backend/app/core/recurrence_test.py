from datetime import datetime, timedelta, timezone
from itertools import islice
from zoneinfo import ZoneInfo

import pytest
from dateutil.rrule import rrulestr

from app.core import recurrence

BERLIN = ZoneInfo("Europe/Berlin")
UTC = timezone.utc

# Monday 00:30 in Berlin is Sunday in UTC.
EAST = datetime(2026, 10, 5, 0, 30, tzinfo=BERLIN)


@pytest.mark.parametrize(
    ("text", "kind", "stored"),
    [
        ("FREQ=MONTHLY;BYDAY=2MO", "task", "RRULE:FREQ=MONTHLY;BYDAY=2MO"),
        ("RRULE:FREQ=HOURLY;BYHOUR=17,9", "event", "RRULE:FREQ=HOURLY;BYHOUR=17,9"),
        (
            "RRULE:FREQ=WEEKLY;BYDAY=MO\nRDATE;VALUE=DATE:20261224\n"
            "EXDATE:20261012T063000Z",
            "event",
            "RRULE:FREQ=WEEKLY;BYDAY=MO\nEXDATE:20261012T063000Z\n"
            "RDATE;VALUE=DATE:20261224",
        ),
    ],
)
def test_normalize_writes_canonical_lines(text, kind, stored):
    assert recurrence.normalize(text, kind=kind) == stored


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("FREQ=HOURLY", "task"),
        ("FREQ=DAILY;BYHOUR=9", "task"),
        ("FREQ=MINUTELY", "event"),
        ("FREQ=DAILY;BYMINUTE=5", "event"),
        ("FREQ=DAILY;COUNT=3;UNTIL=20261201T000000Z", "event"),
        ("FREQ=DAILY;UNTIL=20261201T000000", "event"),
        ("FREQ=DAILY;INTERVAL=0", "event"),
        ("FREQ=DAILY;COUNT=10001", "event"),
        ("FREQ=BOGUS", "event"),
        ("DTSTART:20261001T000000Z\nRRULE:FREQ=DAILY", "event"),
        ("", "event"),
    ],
)
def test_normalize_refuses(text, kind):
    with pytest.raises(ValueError):
        recurrence.normalize(text, kind=kind)


_PICKED = [
    rule
    for interval in (1, 2)
    for rule in (
        f"FREQ=WEEKLY;INTERVAL={interval};BYDAY=MO,TH",
        f"FREQ=MONTHLY;INTERVAL={interval};BYDAY=5MO",
        f"FREQ=MONTHLY;INTERVAL={interval};BYDAY=-1MO",
        f"FREQ=MONTHLY;INTERVAL={interval};BYMONTHDAY=29",
        f"FREQ=MONTHLY;INTERVAL={interval};BYMONTHDAY=30",
        f"FREQ=MONTHLY;INTERVAL={interval};BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1",
        f"FREQ=MONTHLY;INTERVAL={interval};BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
        f"FREQ=YEARLY;INTERVAL={interval};BYMONTH=2;BYMONTHDAY=28",
        f"FREQ=WEEKLY;INTERVAL={interval};BYDAY=MO;BYHOUR=0,12",
        f"FREQ=DAILY;INTERVAL={interval};BYHOUR=0,12",
    )
]


@pytest.mark.parametrize("picked", _PICKED)
@pytest.mark.parametrize(
    ("zone", "at"),
    [
        (BERLIN, (0, 30)),
        (ZoneInfo("America/New_York"), (20, 30)),
        (ZoneInfo("Asia/Kolkata"), (0, 15)),
        (ZoneInfo("Pacific/Auckland"), (1, 0)),
    ],
    ids=["berlin-midnight", "new-york-evening", "kolkata-midnight", "auckland"],
)
def test_a_stored_rule_starts_when_it_was_picked_to(picked, zone, at):
    """Near midnight a day moves across a month's end on some months and not
    others, which no rule in UTC terms can say. Kept as picked, with its
    shift, the rule starts exactly when it does at the start's own offset."""
    first = rrulestr(f"RRULE:{picked}", dtstart=datetime(2026, 1, 1, *at))[0].replace(
        tzinfo=zone
    )
    fixed = timezone(first.utcoffset() or timedelta(0))
    wanted = [
        value.replace(tzinfo=fixed).astimezone(UTC)
        for value in islice(
            rrulestr(f"RRULE:{picked}", dtstart=first.replace(tzinfo=None)), 60
        )
    ]
    rule, shift = recurrence.stored(picked, first, str(zone), kind="event")
    assert rule == recurrence.normalize(picked, kind="event")
    assert recurrence.first(rule, first, shift, 60) == wanted


def test_occurrences_come_from_the_stored_rule():
    rule, shift = recurrence.stored(
        "FREQ=WEEKLY;BYDAY=MO,WE", EAST, "Europe/Berlin", kind="event"
    )
    assert shift == 1440
    start = EAST.astimezone(UTC)
    assert recurrence.next_start(rule, start, shift) == datetime(
        2026, 10, 6, 22, 30, tzinfo=UTC
    )
    # A task series' own counter decides its end, so COUNT can be left out.
    assert recurrence.next_start("RRULE:FREQ=DAILY;COUNT=1", start) is None
    assert recurrence.next_start(
        "RRULE:FREQ=DAILY;COUNT=1", start, count=False
    ) == datetime(2026, 10, 5, 22, 30, tzinfo=UTC)
    assert recurrence.last_start("RRULE:FREQ=WEEKLY;COUNT=3", start) == datetime(
        2026, 10, 18, 22, 30, tzinfo=UTC
    )
    # A task series' successor counts down what its predecessors used.
    assert recurrence.last_start(
        "RRULE:FREQ=WEEKLY;COUNT=3", start, done=1
    ) == datetime(2026, 10, 11, 22, 30, tzinfo=UTC)
    assert recurrence.last_start("RRULE:FREQ=DAILY;UNTIL=20261201", start) == (
        datetime(2026, 12, 1, 23, 59, 59, tzinfo=UTC)
    )
    assert recurrence.last_start("RRULE:FREQ=DAILY", start) is None
    # An extra start after the end, given as a date, is the last one.
    assert recurrence.last_start(
        "RRULE:FREQ=DAILY;UNTIL=20261201\nRDATE;VALUE=DATE:20261224", start
    ) == datetime(2026, 12, 24, 22, 30, tzinfo=UTC)
    assert recurrence.between(
        "RRULE:FREQ=WEEKLY;BYDAY=MO\nEXDATE:20261011T223000Z\nRDATE:20261020T090000Z",
        start,
        shift,
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 10, 21, tzinfo=UTC),
    ) == [
        datetime(2026, 10, 4, 22, 30, tzinfo=UTC),
        datetime(2026, 10, 18, 22, 30, tzinfo=UTC),
        datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
    ]


def test_a_repeat_moves_with_its_start():
    """Mondays at 00:30 in Berlin, moved to noon: still Mondays, the shift
    taken again, and a skipped Monday skipped at its new time."""
    rule = "RRULE:FREQ=WEEKLY;BYDAY=MO\nEXDATE:20261011T223000Z"
    noon = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
    moved, shift = recurrence.restarted(rule, 1440, EAST, noon, "Europe/Berlin")
    assert (moved, shift) == (
        "RRULE:FREQ=WEEKLY;BYDAY=MO\nEXDATE:20261012T100000Z",
        0,
    )
    # Without a zone the shift stays.
    assert recurrence.restarted(rule, 1440, EAST, noon, None)[1] == 1440


def test_imports_read_either_shape():
    """A rule string comes with its shift; the JSON shape older exports carried
    was picked in a zone, which the importer's stands in for."""
    assert recurrence.imported(
        "FREQ=WEEKLY;BYDAY=MO", kind="task", start=EAST, tz="Europe/Berlin", shift=1440
    ) == ("RRULE:FREQ=WEEKLY;BYDAY=MO", 1440)
    legacy = {"frequency": "weekly", "weekdays": ["monday"], "ends": "never"}
    assert recurrence.imported(legacy, kind="task", start=EAST, tz="Europe/Berlin") == (
        "RRULE:FREQ=WEEKLY;BYDAY=MO",
        1440,
    )
    assert recurrence.imported(
        {"frequency": "hourly"}, kind="event", start=EAST, tz=None
    ) == (None, 0)
