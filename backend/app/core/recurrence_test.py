from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core import recurrence

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc

# Monday 00:30 in Berlin is Sunday in UTC; Monday 20:30 in New York is Tuesday.
EAST = datetime(2026, 10, 5, 0, 30, tzinfo=BERLIN)
WEST = datetime(2026, 10, 26, 20, 30, tzinfo=NEW_YORK)
NOON = datetime(2026, 10, 5, 12, 0, tzinfo=BERLIN)


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


@pytest.mark.parametrize("start", [EAST, WEST, NOON])
@pytest.mark.parametrize(
    "picked",
    [
        "FREQ=DAILY;INTERVAL=3",
        "FREQ=WEEKLY;BYDAY=MO,WE",
        "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH",
        "FREQ=MONTHLY;BYMONTHDAY=1,15",
        "FREQ=MONTHLY;BYMONTHDAY=31",
        "FREQ=MONTHLY;BYMONTHDAY=-1",
        "FREQ=MONTHLY;BYDAY=2MO",
        "FREQ=MONTHLY;BYDAY=-1FR",
        "FREQ=MONTHLY;BYDAY=MO",
        "FREQ=YEARLY;BYMONTH=11;BYDAY=4TH",
        "FREQ=YEARLY;BYMONTH=12;BYMONTHDAY=31",
        "FREQ=YEARLY;INTERVAL=2;BYMONTH=6;BYMONTHDAY=30",
    ],
)
def test_picked_days_are_stored_exactly_and_read_back(picked, start):
    """Every rule the form builds is stored in UTC terms that start at the same
    instants, and reads back as it was picked."""
    zone = start.tzinfo
    stored = recurrence.to_utc_terms(picked, start, zone)
    assert recurrence.is_exact(picked, stored, start, zone)
    assert recurrence.to_local_terms(stored, start, zone) == recurrence.normalize(
        picked, kind="event"
    )


def test_utc_terms_move_the_days_with_the_start():
    assert recurrence.to_utc_terms("FREQ=MONTHLY;BYDAY=2MO", EAST, BERLIN) == (
        "RRULE:FREQ=MONTHLY;BYDAY=SU;BYMONTHDAY=7,8,9,10,11,12,13"
    )
    # The last work day is one of a month's last three days, pinned so the
    # day before it stays exact.
    assert recurrence.to_utc_terms(
        "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1", EAST, BERLIN
    ) == ("RRULE:FREQ=MONTHLY;BYDAY=SU,MO,TU,WE,TH;BYMONTHDAY=-4,-3,-2;BYSETPOS=-1")
    assert (
        recurrence.to_utc_terms("FREQ=DAILY;BYHOUR=0,9", NOON, BERLIN)
        == "RRULE:FREQ=DAILY;BYHOUR=7,22"
    )
    # A start whose day is the same in UTC changes nothing.
    assert recurrence.to_utc_terms("FREQ=WEEKLY;BYDAY=MO", NOON, BERLIN) == (
        "RRULE:FREQ=WEEKLY;BYDAY=MO"
    )


def test_a_rule_with_no_exact_utc_form_is_the_nearest_one():
    """The day after the last work day can fall in the next month, which one
    rule can't say; the nearest is stored and reported as not exact."""
    picked = "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1"
    stored = recurrence.to_utc_terms(picked, WEST, NEW_YORK)
    assert stored == "RRULE:FREQ=MONTHLY;BYDAY=TU,WE,TH,FR,SA;BYSETPOS=-1"
    assert not recurrence.is_exact(picked, stored, WEST, NEW_YORK)


def test_occurrences_come_from_the_stored_rule():
    start = datetime(2026, 10, 4, 22, 30, tzinfo=UTC)
    assert recurrence.next_start("RRULE:FREQ=WEEKLY;BYDAY=SU,TU", start) == (
        datetime(2026, 10, 6, 22, 30, tzinfo=UTC)
    )
    # A task series' own counter decides its end, so COUNT can be left out.
    assert recurrence.next_start("RRULE:FREQ=DAILY;COUNT=1", start) is None
    assert recurrence.next_start(
        "RRULE:FREQ=DAILY;COUNT=1", start, count=False
    ) == datetime(2026, 10, 5, 22, 30, tzinfo=UTC)
    assert recurrence.last_start("RRULE:FREQ=WEEKLY;COUNT=3", start) == datetime(
        2026, 10, 18, 22, 30, tzinfo=UTC
    )
    assert recurrence.last_start("RRULE:FREQ=DAILY;UNTIL=20261201", start) == (
        datetime(2026, 12, 1, 23, 59, 59, tzinfo=UTC)
    )
    assert recurrence.last_start("RRULE:FREQ=DAILY", start) is None
    assert recurrence.between(
        "RRULE:FREQ=WEEKLY;BYDAY=SU\nEXDATE:20261011T223000Z\nRDATE:20261020T090000Z",
        start,
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 10, 21, tzinfo=UTC),
    ) == [
        datetime(2026, 10, 4, 22, 30, tzinfo=UTC),
        datetime(2026, 10, 18, 22, 30, tzinfo=UTC),
        datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
    ]
