"""Jira's JSON as this app's project envelope.

The load-bearing test here is the last one: whatever the mapping produces has
to validate as a real ``ProjectExportEnvelope``, because the apply path is
the one that has existed for months and knows nothing about Jira. A mapping
that produces something almost-right would fail at apply time, inside a
worker, long after the person who started the import went away.
"""

import pytest

from app.models.tenant.task import TaskPriority, TaskStatusCategory
from app.services.import_engine import jira_mapping as jm

pytestmark = pytest.mark.unit


def _status(name, category_key, status_id=None):
    out = {"name": name, "statusCategory": {"key": category_key}}
    if status_id is not None:
        out["id"] = str(status_id)
    return out


def _issue(key, summary, *, status="To Do", **fields):
    return {
        "key": key,
        "fields": {"summary": summary, "status": {"name": status}, **fields},
    }


# --- priority --------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Highest", TaskPriority.urgent),
        ("High", TaskPriority.high),
        ("Medium", TaskPriority.medium),
        ("Low", TaskPriority.low),
        # Jira has five, we have four: the bottom two collapse.
        ("Lowest", TaskPriority.low),
        ("  hIgH  ", TaskPriority.high),
    ],
)
def test_priority_is_matched_by_name(name, expected):
    """By name, not id — ids are per-site, the five names are Jira's own."""
    assert jm.map_priority({"name": name}) is expected


@pytest.mark.parametrize("field", [None, {}, {"name": "Blocker"}, "High", 7])
def test_an_unreadable_priority_is_medium(field):
    assert jm.map_priority(field) is TaskPriority.medium


# --- statuses --------------------------------------------------------------


@pytest.mark.parametrize(
    "jira_status,expected",
    [
        (_status("To Do", "new"), TaskStatusCategory.todo),
        (_status("In Progress", "indeterminate"), TaskStatusCategory.in_progress),
        (_status("Done", "done"), TaskStatusCategory.done),
        # The one status name worth reading: we have a category for it and
        # Jira does not.
        (_status("Backlog", "new"), TaskStatusCategory.backlog),
        (_status("backlog", "new"), TaskStatusCategory.backlog),
        # A "Backlog" that Jira says is in flight is in flight.
        (_status("Backlog", "indeterminate"), TaskStatusCategory.in_progress),
    ],
)
def test_a_status_lands_by_jira_category(jira_status, expected):
    assert jm.map_status_category(jira_status) is expected


def test_statuses_are_the_union_over_issue_types():
    """Jira reports statuses per issue type, so the same one arrives twice."""
    statuses = jm.collect_statuses(
        [
            {
                "name": "Story",
                "statuses": [_status("To Do", "new"), _status("Done", "done")],
            },
            {
                "name": "Bug",
                "statuses": [_status("To Do", "new"), _status("Triage", "new")],
            },
        ]
    )
    assert [s["name"] for s in statuses] == ["To Do", "Done", "Triage"]


def test_the_board_decides_the_order_and_strays_follow():
    """The board is the order a team arranged; the workflow is the order Jira
    happens to list. A status the board does not show still has to exist, or
    the issues in it would have nowhere to land."""
    statuses = jm.collect_statuses(
        [
            {
                "statuses": [
                    _status("Done", "done"),
                    _status("To Do", "new"),
                    _status("In Progress", "indeterminate"),
                    _status("Archived", "done"),
                ]
            }
        ],
        board_column_order=["To Do", "In Progress", "Done"],
    )
    assert [s["name"] for s in statuses] == [
        "To Do",
        "In Progress",
        "Done",
        "Archived",
    ]
    assert [s["position"] for s in statuses] == [0, 1, 2, 3]


def test_the_default_is_the_first_not_started_column():
    statuses = jm.collect_statuses(
        [
            {
                "statuses": [
                    _status("In Progress", "indeterminate"),
                    _status("Backlog", "new"),
                    _status("Done", "done"),
                ]
            }
        ]
    )
    defaults = [s["name"] for s in statuses if s["is_default"]]
    assert defaults == ["Backlog"]


def test_a_workflow_with_nothing_unstarted_still_has_a_default():
    """Something has to be default, and the first column is the least
    surprising answer."""
    statuses = jm.collect_statuses(
        [
            {
                "statuses": [
                    _status("In Progress", "indeterminate"),
                    _status("Done", "done"),
                ]
            }
        ]
    )
    assert statuses[0]["is_default"] is True
    assert sum(s["is_default"] for s in statuses) == 1


def test_board_columns_flatten_to_their_status_names():
    """A column can hold several statuses; the flattened sequence is the
    board's reading order."""
    configuration = {
        "columnConfig": {
            "columns": [
                {"name": "To Do", "statuses": [{"id": "1"}]},
                {"name": "Doing", "statuses": [{"id": "2"}, {"id": "3"}]},
            ]
        }
    }
    names = jm.board_column_status_names(
        configuration, {"1": "To Do", "2": "In Progress", "3": "In Review"}
    )
    assert names == ["To Do", "In Progress", "In Review"]


@pytest.mark.parametrize("bad", [None, {}, {"columnConfig": None}, "nope"])
def test_a_board_we_cannot_read_just_has_no_opinion(bad):
    assert jm.board_column_status_names(bad, {}) == []


# --- issues ----------------------------------------------------------------


def _map(issue, **kw):
    return jm.map_issue(
        issue,
        position=kw.pop("position", 1000.0),
        status_names=kw.pop("status_names", {"To Do", "Done"}),
        default_status_name=kw.pop("default_status_name", "To Do"),
    )


def test_an_issue_becomes_a_task():
    task = _map(
        _issue(
            "ACME-1",
            "Fit the door",
            status="Done",
            priority={"name": "High"},
            labels=["joinery", "urgent"],
            assignee={"displayName": "Alice Chen"},
            duedate="2026-03-04",
            created="2024-03-04T09:30:00.000+0000",
        )
    )
    assert task["title"] == "Fit the door"
    assert task["status_name"] == "Done"
    assert task["priority"] == "high"
    assert [t["name"] for t in task["tags"]] == ["joinery", "urgent"]
    assert task["assignee_handles"] == ["Alice Chen"]
    assert task["due_date"].startswith("2026-03-04")
    assert task["created_at"].startswith("2024-03-04")
    assert task["external_ref"] == "jira:ACME-1"


def test_an_issue_in_an_unknown_status_lands_in_the_default():
    """A workflow can change mid-fetch. Inventing a column would be worse."""
    task = _map(_issue("ACME-2", "Stray", status="Somewhere Else"))
    assert task["status_name"] == "To Do"


def test_a_description_becomes_markdown_and_gives_up_its_checkboxes():
    task = _map(
        _issue(
            "ACME-3",
            "With a body",
            description={
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Do it"}],
                    },
                    {
                        "type": "taskList",
                        "content": [
                            {
                                "type": "taskItem",
                                "attrs": {"state": "DONE"},
                                "content": [{"type": "text", "text": "measured"}],
                            }
                        ],
                    },
                ],
            },
        )
    )
    assert task["description"] == "Do it"
    assert task["checklist"] == [{"text": "measured", "done": True}]


def test_labels_are_deduplicated_case_insensitively():
    task = _map(_issue("ACME-4", "Tagged", labels=["Bug", "bug", " ", "ui"]))
    assert [t["name"] for t in task["tags"]] == ["Bug", "ui"]


def test_an_assignee_travels_as_a_name_never_an_address():
    """Jira nulls emailAddress under the account's own privacy settings, and
    who somebody is here is the wizard's question anyway."""
    task = _map(
        _issue(
            "ACME-5",
            "Assigned",
            assignee={
                "displayName": "Alice Chen",
                "emailAddress": "alice@example.com",
            },
        )
    )
    assert task["assignee_handles"] == ["Alice Chen"]
    assert "alice@example.com" not in str(task)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "not an issue",
        {"key": "ACME-9"},
        {"key": "ACME-9", "fields": {"summary": "   "}},
        {"key": "ACME-9", "fields": "nope"},
    ],
)
def test_a_malformed_issue_is_skipped_not_fatal(bad):
    """The search API is somebody else's. One bad row must not take the
    fetch down with it."""
    assert _map(bad) is None


# --- the whole envelope ----------------------------------------------------


def _envelope(**kw):
    return jm.build_project_envelope(
        project=kw.pop("project", {"key": "ACME", "name": "Acme Board"}),
        issue_type_statuses=kw.pop(
            "issue_type_statuses",
            [{"statuses": [_status("To Do", "new"), _status("Done", "done")]}],
        ),
        issues=kw.pop("issues", [_issue("ACME-1", "One"), _issue("ACME-2", "Two")]),
        app_version="0.0.0-test",
        **kw,
    )


def test_rank_order_becomes_position_order():
    """Jira's rank is an opaque LexoRank string that means nothing here, so
    the sequence it arrives in is the thing that carries the order."""
    envelope = _envelope()
    positions = [t["position"] for t in envelope["tasks"]]
    assert positions == sorted(positions)
    assert positions[0] < positions[1]


def test_the_project_declares_every_tag_its_tasks_use():
    envelope = _envelope(
        issues=[
            _issue("ACME-1", "One", labels=["ui"]),
            _issue("ACME-2", "Two", labels=["ui", "api"]),
        ]
    )
    assert [t["name"] for t in envelope["tags"]] == ["ui", "api"]


def test_a_project_with_no_workflow_still_produces_something_applyable():
    """The importer refuses an envelope with no statuses, so the fetch must
    never produce one — even from a site that answers oddly."""
    envelope = _envelope(issue_type_statuses=[])
    assert len(envelope["task_statuses"]) == 1
    assert envelope["task_statuses"][0]["is_default"] is True


def test_malformed_issues_are_dropped_from_the_envelope():
    envelope = _envelope(issues=[_issue("ACME-1", "Good"), None, {"nope": True}])
    assert [t["title"] for t in envelope["tasks"]] == ["Good"]


def test_what_the_mapping_produces_is_a_real_envelope():
    """The one that matters. The apply path predates Jira by months and will
    not bend to it — whatever comes out of here has to validate as the same
    envelope a project export writes, or the import fails inside a worker
    long after anybody is watching.
    """
    from app.schemas.tenant.project_export import ProjectExportEnvelope

    envelope = _envelope(
        issues=[
            _issue(
                "ACME-1",
                "Fit the door",
                status="Done",
                priority={"name": "Highest"},
                labels=["joinery"],
                assignee={"displayName": "Alice Chen"},
                duedate="2026-03-04",
                created="2024-03-04T09:30:00.000+0000",
                updated="2024-05-01T12:00:00.000+0000",
                description={
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Body"}],
                        }
                    ],
                },
            )
        ],
        board_column_order=["To Do", "Done"],
        site_url="https://acme.atlassian.net",
    )

    parsed = ProjectExportEnvelope.model_validate(envelope)
    assert parsed.project.name == "Acme Board"
    assert parsed.tasks[0].title == "Fit the door"
    assert parsed.tasks[0].priority is TaskPriority.urgent
    assert parsed.tasks[0].external_ref == "jira:ACME-1"
    assert parsed.task_statuses[0].name == "To Do"
