"""Unit tests for the completed_at rule.

The endpoint-level coverage — every path that can move a task across the done
boundary — lives in
``app/api/v1/tenant_endpoints/task_completion_test.py``.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.models.tenant.task import Task, TaskStatusCategory
from app.services.tenant.task_completion import sync_completed_at

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
EARLIER = NOW - timedelta(days=3)


def _task(**overrides: Any) -> Task:
    return Task(project_id=1, task_status_id=1, title="t", **overrides)


@pytest.mark.unit
def test_entering_done_stamps_the_timestamp():
    task = _task()

    sync_completed_at(task, TaskStatusCategory.done, now=NOW)

    assert task.completed_at == NOW


@pytest.mark.unit
@pytest.mark.parametrize(
    "category",
    [
        TaskStatusCategory.backlog,
        TaskStatusCategory.todo,
        TaskStatusCategory.in_progress,
    ],
)
def test_leaving_done_clears_the_timestamp(category: TaskStatusCategory):
    task = _task(completed_at=EARLIER)

    sync_completed_at(task, category, now=NOW)

    assert task.completed_at is None


@pytest.mark.unit
def test_staying_done_keeps_the_original_time():
    """Moving between two done statuses is not a re-completion."""
    task = _task(completed_at=EARLIER)

    sync_completed_at(task, TaskStatusCategory.done, now=NOW)

    assert task.completed_at == EARLIER


@pytest.mark.unit
def test_staying_incomplete_is_a_no_op():
    task = _task()

    sync_completed_at(task, TaskStatusCategory.todo, now=NOW)

    assert task.completed_at is None


@pytest.mark.unit
def test_unknown_category_is_treated_as_incomplete():
    """A caller that cannot resolve a status (a bulk creator whose mapping
    missed) must not leave a stale completion behind."""
    task = _task(completed_at=EARLIER)

    sync_completed_at(task, None, now=NOW)

    assert task.completed_at is None


@pytest.mark.unit
def test_rule_is_idempotent():
    task = _task()

    sync_completed_at(task, TaskStatusCategory.done, now=NOW)
    sync_completed_at(task, TaskStatusCategory.done, now=NOW + timedelta(hours=1))

    assert task.completed_at == NOW
