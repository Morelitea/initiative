"""Vikunja's ``data.json`` as this app's project envelope.

As with every mapper here, the last test is the load-bearing one: the result
has to validate as a real ``ProjectExportEnvelope``, because the apply path
knows nothing about Vikunja.
"""

import json

import pytest

from app.core.relationships import RelationshipType
from app.models.tenant.task import TaskPriority, TaskStatusCategory
from app.schemas.tenant.project_export import ProjectExportEnvelope
from app.services.import_engine import vikunja_mapping as vm


def _task(**over):
    task = {"id": 1, "title": "A task", "done": False}
    task.update(over)
    return task


def _project(**over):
    project = {"id": 7, "title": "Work", "buckets": [], "tasks": []}
    project.update(over)
    return project


def _doc(*projects):
    return json.dumps(list(projects))


def _build(content, selection="7"):
    return vm.build_project_envelope(content, selection=selection, app_version="1.2.3")


# --- the HTML Vikunja writes into a description ----------------------------


def test_a_checklist_is_lifted_out_of_the_description():
    html = (
        "<p>Do the thing</p>"
        '<ul data-type="taskList">'
        '<li data-checked="true" data-type="taskItem"><p>First</p></li>'
        '<li data-checked="false" data-type="taskItem"><p>Second</p></li>'
        "</ul>"
    )
    items, remaining = vm.extract_task_list_items(html)
    assert items == [
        {"content": "First", "is_completed": True},
        {"content": "Second", "is_completed": False},
    ]
    assert "taskItem" not in remaining
    assert vm.html_to_markdown(remaining) == "Do the thing"


def test_html_becomes_markdown():
    """A heading ends at its line break, so one newline after it is enough."""
    html = "<h2>Heading</h2><p>Some <strong>bold</strong> and <em>italic</em>.</p>"
    assert vm.html_to_markdown(html) == "## Heading\nSome **bold** and *italic*."


def test_entities_are_decoded():
    assert vm.html_to_markdown("<p>a &amp; b &lt;c&gt;</p>") == "a & b <c>"


def test_empty_html_is_nothing():
    assert vm.html_to_markdown("") == ""
    assert vm.extract_task_list_items("") == ([], "")


# --- which project --------------------------------------------------------


def test_preview_lists_projects_with_tasks_largest_first():
    content = _doc(
        _project(id=1, title="Small", tasks=[_task()]),
        _project(id=2, title="Big", tasks=[_task(), _task(), _task()]),
        _project(id=3, title="Empty", tasks=[]),
    )
    assert [(o.key, o.name, o.task_count) for o in vm.preview(content)] == [
        ("2", "Big", 3),
        ("1", "Small", 1),
    ]


def test_a_document_that_is_not_an_array_is_refused():
    with pytest.raises(ValueError):
        vm.preview(json.dumps({"projects": []}))


def test_choosing_a_project_that_is_not_there_is_refused():
    with pytest.raises(ValueError):
        _build(_doc(_project(id=7)), selection="99")


# --- the fields the old importer dropped -----------------------------------


def test_labels_become_tags():
    mapped = _build(
        _doc(
            _project(
                tasks=[
                    _task(labels=[{"title": "urgent"}, {"title": "Urgent"}, {}]),
                ]
            )
        )
    )
    assert mapped.envelope["tasks"][0]["tags"] == [
        {"name": "urgent", "color": "#6366F1"}
    ]


def test_dates_come_across_and_the_zero_stamp_does_not():
    mapped = _build(
        _doc(
            _project(
                tasks=[
                    _task(
                        due_date="2026-03-09T15:02:00Z",
                        start_date="0001-01-01T00:00:00Z",
                        created="2026-02-01T08:00:00Z",
                    )
                ]
            )
        )
    )
    task = mapped.envelope["tasks"][0]
    assert task["due_date"].startswith("2026-03-09")
    assert task["created_at"].startswith("2026-02-01")
    assert "start_date" not in task


def test_a_finished_task_records_when():
    mapped = _build(
        _doc(_project(tasks=[_task(done=True, done_at="2026-03-10T11:00:00Z")]))
    )
    assert mapped.envelope["tasks"][0]["completed_at"].startswith("2026-03-10")


def test_an_unfinished_task_records_no_completion_even_with_a_stamp():
    mapped = _build(
        _doc(_project(tasks=[_task(done=False, done_at="2026-03-10T11:00:00Z")]))
    )
    assert "completed_at" not in mapped.envelope["tasks"][0]


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0, TaskPriority.low),
        (2, TaskPriority.medium),
        (3, TaskPriority.high),
        (4, TaskPriority.urgent),
        (5, TaskPriority.urgent),
    ],
)
def test_priority_collapses_six_levels_onto_four(raw, expected):
    mapped = _build(_doc(_project(tasks=[_task(priority=raw)])))
    assert mapped.envelope["tasks"][0]["priority"] == expected.value


def test_buckets_become_statuses():
    mapped = _build(
        _doc(
            _project(
                buckets=[{"id": 1, "title": "Backlog"}, {"id": 2, "title": "Done"}],
                tasks=[_task(bucket_id=2)],
            )
        )
    )
    statuses = mapped.envelope["task_statuses"]
    assert [s["name"] for s in statuses] == ["Backlog", "Done"]
    assert statuses[1]["category"] == TaskStatusCategory.done.value
    assert mapped.envelope["tasks"][0]["status_name"] == "Done"


def test_a_task_whose_bucket_is_gone_lands_in_a_column_of_its_own():
    mapped = _build(
        _doc(
            _project(
                buckets=[{"id": 1, "title": "Backlog"}], tasks=[_task(bucket_id=9)]
            )
        )
    )
    assert mapped.envelope["tasks"][0]["status_name"] == vm.NO_BUCKET
    assert vm.NO_BUCKET in [s["name"] for s in mapped.envelope["task_statuses"]]


def test_assignees_come_across_by_username():
    mapped = _build(
        _doc(
            _project(
                tasks=[_task(assignees=[{"username": "sam"}, {"username": "sam"}])]
            )
        )
    )
    assert mapped.envelope["tasks"][0]["assignee_handles"] == ["sam"]


def test_the_identifier_becomes_an_external_ref():
    mapped = _build(_doc(_project(tasks=[_task(id=41)])))
    assert mapped.envelope["tasks"][0]["external_ref"] == "vikunja:41"


# --- relations ------------------------------------------------------------


def test_relations_this_task_can_assert_become_links():
    mapped = _build(
        _doc(
            _project(
                tasks=[
                    _task(
                        id=1,
                        related_tasks={
                            "parenttask": [{"id": 2}],
                            "blocked": [{"id": 3}],
                            "related": [{"id": 4}],
                        },
                    )
                ]
            )
        )
    )
    assert mapped.envelope["tasks"][0]["links"] == [
        {"type": RelationshipType.part_of.value, "target_external_ref": "vikunja:2"},
        {"type": RelationshipType.depends_on.value, "target_external_ref": "vikunja:3"},
        {"type": RelationshipType.related_to.value, "target_external_ref": "vikunja:4"},
    ]


def test_the_reverse_half_of_a_relation_is_left_for_the_other_end_to_assert():
    """ "This task has subtask X" is a claim about X, and X makes it itself
    through its own ``parenttask``. Writing both would double every edge."""
    mapped = _build(
        _doc(_project(tasks=[_task(id=1, related_tasks={"subtask": [{"id": 2}]})]))
    )
    assert mapped.envelope["tasks"][0]["links"] == []


# --- the one that matters --------------------------------------------------


def test_the_envelope_validates_as_a_real_project_export():
    mapped = _build(
        _doc(
            _project(
                title="Work",
                description="<p>The <strong>plan</strong></p>",
                buckets=[{"id": 1, "title": "Doing"}],
                tasks=[
                    _task(
                        id=1,
                        title="Ship it",
                        description=(
                            "<p>Detail</p>"
                            '<ul data-type="taskList">'
                            '<li data-checked="true" data-type="taskItem"><p>Step</p></li>'
                            "</ul>"
                        ),
                        bucket_id=1,
                        priority=4,
                        labels=[{"title": "release"}],
                        due_date="2026-03-09T15:02:00Z",
                        related_tasks={"related": [{"id": 2}]},
                    ),
                    _task(id=2, title="Other", bucket_id=1),
                ],
            )
        )
    )
    envelope = ProjectExportEnvelope.model_validate(mapped.envelope)
    assert envelope.project.name == "Work"
    assert envelope.project.description == "The **plan**"
    first = envelope.tasks[0]
    assert first.title == "Ship it"
    assert first.description == "Detail"
    assert first.priority == TaskPriority.urgent
    assert first.checklist[0].text == "Step"
    assert first.checklist[0].done is True
    assert first.links[0].target_external_ref == "vikunja:2"


def test_a_malformed_task_row_is_skipped_and_counted():
    mapped = _build(
        _doc(_project(tasks=[_task(title="   "), "not a dict", _task(id=2)]))
    )
    assert len(mapped.envelope["tasks"]) == 1
    assert mapped.skipped_rows == 2
