"""Todoist's CSV as this app's project envelope.

The load-bearing test is the last one: whatever the mapping produces has to
validate as a real ``ProjectExportEnvelope``, because the apply path is the
one that has existed for months and knows nothing about Todoist. Something
almost-right would fail at apply time, inside a worker, long after the person
who started the import went away.
"""

import pytest

from app.models.tenant.task import TaskPriority, TaskStatusCategory
from app.schemas.tenant.project_export import ProjectExportEnvelope
from app.services.import_engine import todoist_mapping as tm


HEADER = (
    "TYPE,CONTENT,DESCRIPTION,PRIORITY,INDENT,AUTHOR,RESPONSIBLE,DATE,"
    "DATE_LANG,TIMEZONE,DURATION,DURATION_UNIT,meta,DEADLINE,DEADLINE_LANG\n"
)


def _csv(*rows: str) -> str:
    return HEADER + "".join(row if row.endswith("\n") else row + "\n" for row in rows)


def _build(content: str, name: str = "My project"):
    return tm.build_project_envelope(content, selection=name, app_version="1.2.3")


def _titles(envelope):
    return [task["title"] for task in envelope["tasks"]]


# --- reading the file ------------------------------------------------------


def test_a_bom_and_a_semicolon_file_still_read():
    """A CSV that went through a spreadsheet comes back with a BOM, and in
    some locales with semicolons. Both are the same file."""
    semis = HEADER.replace(",", ";") + "task;Write it up;;1;1;;;;;;;;;;\n"
    mapped = _build("﻿" + semis)
    assert _titles(mapped.envelope) == ["Write it up"]


def test_meta_rows_are_not_tasks():
    mapped = _build(_csv("meta,,,,,,,,,,,,view_style=board,,"))
    assert mapped.envelope["tasks"] == []


def test_a_row_with_no_content_is_skipped_and_counted():
    mapped = _build(_csv("task,,,4,1,,,,,,,,,,"))
    assert mapped.envelope["tasks"] == []
    assert mapped.skipped_rows == 1


# --- sections become statuses ----------------------------------------------


def test_sections_become_statuses_in_file_order():
    mapped = _build(
        _csv(
            "section,Planned,,,,,,,,,,,,,",
            "task,First,,4,1,,,,,,,,,,",
            "section,Done,,,,,,,,,,,,,",
            "task,Second,,4,1,,,,,,,,,,",
        )
    )
    statuses = mapped.envelope["task_statuses"]
    assert [s["name"] for s in statuses] == ["Planned", "Done"]
    assert statuses[1]["category"] == TaskStatusCategory.done.value
    assert [t["status_name"] for t in mapped.envelope["tasks"]] == ["Planned", "Done"]


def test_tasks_before_any_section_get_their_own_first_column():
    mapped = _build(
        _csv(
            "task,Loose,,4,1,,,,,,,,,,",
            "section,Later,,,,,,,,,,,,,",
            "task,Filed,,4,1,,,,,,,,,,",
        )
    )
    names = [s["name"] for s in mapped.envelope["task_statuses"]]
    assert names == [tm.UNSECTIONED, "Later"]
    assert mapped.envelope["tasks"][0]["status_name"] == tm.UNSECTIONED


def test_a_file_with_no_sections_still_has_a_column():
    mapped = _build(_csv("task,Only,,4,1,,,,,,,,,,"))
    assert len(mapped.envelope["task_statuses"]) == 1
    assert mapped.envelope["task_statuses"][0]["is_default"] is True


# --- the fields the old importer dropped -----------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1", TaskPriority.urgent),
        ("2", TaskPriority.high),
        ("3", TaskPriority.medium),
        ("4", TaskPriority.low),
        ("", TaskPriority.low),
        ("nonsense", TaskPriority.low),
    ],
)
def test_priority_counts_down(raw, expected):
    mapped = _build(_csv(f"task,T,,{raw},1,,,,,,,,,,"))
    assert mapped.envelope["tasks"][0]["priority"] == expected.value


def test_a_note_row_becomes_a_comment_on_the_row_above():
    mapped = _build(
        _csv(
            "task,Ship it,,4,1,,,,,,,,,,",
            "note,Blocked on legal,,,,Dana (42),,,,,,,,,",
        )
    )
    (task,) = mapped.envelope["tasks"]
    assert task["comments"] == [{"author_name": "Dana", "body": "Blocked on legal"}]


def test_a_note_with_no_task_above_it_is_counted_not_attached():
    mapped = _build(_csv("note,Orphaned,,,,,,,,,,,,,"))
    assert mapped.envelope["tasks"] == []
    assert mapped.skipped_rows == 1


def test_a_deadline_is_the_due_date_and_the_date_becomes_the_start():
    mapped = _build(_csv("task,T,,4,1,,,2026-03-01,,,,,,2026-03-09,"))
    task = mapped.envelope["tasks"][0]
    assert task["due_date"].startswith("2026-03-09")
    assert task["start_date"].startswith("2026-03-01")


def test_a_lone_date_is_the_due_date():
    mapped = _build(_csv("task,T,,4,1,,,2026-03-01,,,,,,,"))
    task = mapped.envelope["tasks"][0]
    assert task["due_date"].startswith("2026-03-01")
    assert "start_date" not in task


def test_a_recurring_date_is_dropped_rather_than_guessed():
    """Todoist writes "every day" in the same column as a date. It is not one."""
    mapped = _build(_csv("task,T,,4,1,,,every day,,,,,,,"))
    assert "due_date" not in mapped.envelope["tasks"][0]


def test_the_responsible_column_becomes_an_assignee():
    mapped = _build(_csv("task,T,,4,1,,Sam Reed (99),,,,,,,,"))
    assert mapped.envelope["tasks"][0]["assignee_handles"] == ["Sam Reed"]


def test_an_indented_row_is_the_checklist_of_the_task_above():
    mapped = _build(
        _csv(
            "task,Parent,,4,1,,,,,,,,,,",
            "task,Step one,,4,2,,,,,,,,,,",
            "task,Step two,,4,3,,,,,,,,,,",
        )
    )
    (task,) = mapped.envelope["tasks"]
    assert [item["text"] for item in task["checklist"]] == ["Step one", "Step two"]


# --- preview ---------------------------------------------------------------


def test_preview_counts_only_top_level_tasks():
    options = tm.preview(
        _csv(
            "task,Parent,,4,1,,,,,,,,,,",
            "task,Child,,4,2,,,,,,,,,,",
            "task,Other,,4,1,,,,,,,,,,",
        )
    )
    assert len(options) == 1
    assert options[0].task_count == 2


def test_preview_of_an_empty_file_says_nothing_is_there():
    assert tm.preview("")[0].task_count == 0


# --- the one that matters --------------------------------------------------


def test_the_envelope_validates_as_a_real_project_export():
    mapped = _build(
        _csv(
            "section,Doing,,,,,,,,,,,,,",
            "task,Ship it,With detail,1,1,,Sam Reed (9),2026-03-01,,,,,,2026-03-09,",
            "task,A step,,4,2,,,,,,,,,,",
            "note,Said something,,,,Dana (42),,,,,,,,,",
        )
    )
    envelope = ProjectExportEnvelope.model_validate(mapped.envelope)
    assert envelope.type == "initiative-project"
    assert envelope.project.name == "My project"
    (task,) = envelope.tasks
    assert task.title == "Ship it"
    assert task.priority == TaskPriority.urgent
    assert task.status_name == "Doing"
    assert task.checklist[0].text == "A step"
    assert task.comments[0].body == "Said something"
    assert task.assignee_handles == ["Sam Reed"]


def test_an_unnamed_import_still_gets_a_project_name():
    mapped = _build(_csv("task,T,,4,1,,,,,,,,,,"), name="")
    ProjectExportEnvelope.model_validate(mapped.envelope)
    assert mapped.envelope["project"]["name"] == "Todoist import"


def test_a_file_with_tasks_warns_that_completed_ones_are_missing():
    """Todoist's export omits completed tasks. The wizard says so; this is
    where that is decided."""
    mapped = _build(_csv("task,T,,4,1,,,,,,,,,,"))
    assert "TODOIST_EXPORT_OMITS_COMPLETED" in mapped.warnings
