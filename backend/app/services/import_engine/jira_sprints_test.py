"""Jira sprints → calendar events (D11)."""

import pytest

from app.services.import_engine import jira_sprints as js


def _sprint(sprint_id=7, **over):
    base = {
        "id": sprint_id,
        "name": f"Sprint {sprint_id}",
        "state": "closed",
        "boardId": 3,
        "goal": "Ship it",
        "startDate": "2024-03-04T09:00:00.000Z",
        "endDate": "2024-03-18T09:00:00.000Z",
        "completeDate": "2024-03-18T10:00:00.000Z",
    }
    base.update(over)
    return base


def test_the_sprint_field_is_found_by_its_type_not_its_id():
    catalog = [
        {"id": "customfield_1", "schema": {"custom": "other"}},
        {"id": "customfield_2", "schema": {"custom": js.SPRINT_FIELD_CUSTOM}},
        "nonsense",
    ]
    assert js.sprint_field_ids(catalog) == ["customfield_2"]
    assert js.sprint_field_ids(None) == []


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "Sprint 7",
        {"name": "No id"},
        {"id": True, "name": "x"},
        {"id": 3, "name": ""},
    ],
)
def test_a_sprint_that_is_not_one_is_skipped(bad):
    assert js.read_sprint(bad) is None


def test_an_issue_carried_over_is_in_both_sprints_once_each():
    issue = {
        "key": "ACME-1",
        "fields": {"customfield_2": [_sprint(7), _sprint(8), _sprint(7)]},
    }
    assert [s.id for s in js.issue_sprints(issue, ["customfield_2"])] == [7, 8]


def test_a_sprint_becomes_one_event_on_its_boards_calendar():
    sprint = js.read_sprint(_sprint(7))
    calendars, placed = js.build_sprint_calendars({7: sprint}, {3: "Door team"})
    assert placed == {7}
    (calendar,) = calendars
    assert calendar["name"] == "Door team"
    (event,) = calendar["events"]
    assert event["title"] == "Sprint 7"
    assert event["external_ref"] == "jira-sprint:7"
    assert event["start_at"].startswith("2024-03-04T09:00:00")
    assert event["end_at"].startswith("2024-03-18T09:00:00")
    assert "**Goal:** Ship it" in event["description"]


def test_a_sprint_never_started_has_no_event():
    """Planned but not begun: no stretch of time to put on a calendar, and
    so no link from its tasks to something that will not exist."""
    sprint = js.read_sprint(_sprint(9, startDate=None, endDate=None, completeDate=None))
    calendars, placed = js.build_sprint_calendars({9: sprint}, {})
    assert calendars == [] and placed == set()


def test_a_sprint_with_no_end_runs_to_when_it_was_completed():
    sprint = js.read_sprint(_sprint(7, endDate=None))
    calendars, _ = js.build_sprint_calendars({7: sprint}, {})
    assert calendars[0]["events"][0]["end_at"].startswith("2024-03-18T10:00:00")


def test_boards_get_a_calendar_each_and_an_unnamed_one_a_fallback():
    sprints = {
        7: js.read_sprint(_sprint(7, boardId=3)),
        8: js.read_sprint(_sprint(8, boardId=4)),
    }
    calendars, _ = js.build_sprint_calendars(sprints, {3: "Door team"})
    assert sorted(c["name"] for c in calendars) == [
        "Door team",
        js.FALLBACK_CALENDAR_NAME,
    ]


def test_a_sprint_calendar_is_a_real_calendar_envelope():
    from app.schemas.tenant.import_envelopes import CalendarEnvelope

    calendars, _ = js.build_sprint_calendars(
        {7: js.read_sprint(_sprint(7))}, {3: "Door team"}
    )
    parsed = CalendarEnvelope.model_validate(calendars[0])
    assert parsed.events[0].external_ref == "jira-sprint:7"
