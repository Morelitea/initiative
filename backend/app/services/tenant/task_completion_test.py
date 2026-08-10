"""Unit tests for the assignment-completion rules.

Endpoint-level coverage — every path that can move a task across the done
boundary, plus marking your own part — lives in
``app/api/v1/tenant_endpoints/task_completion_test.py``.
"""

import pytest

from app.models.tenant.task import TaskStatusCategory
from app.services.tenant.task_completion import left_done

DONE = TaskStatusCategory.done
TODO = TaskStatusCategory.todo
IN_PROGRESS = TaskStatusCategory.in_progress
BACKLOG = TaskStatusCategory.backlog


@pytest.mark.unit
@pytest.mark.parametrize("current", [TODO, IN_PROGRESS, BACKLOG])
def test_leaving_done_for_any_other_column_counts(current: TaskStatusCategory):
    assert left_done(DONE, current) is True


@pytest.mark.unit
def test_staying_in_done_is_not_leaving():
    """Two done columns are still done — nobody's part reopens."""
    assert left_done(DONE, DONE) is False


@pytest.mark.unit
@pytest.mark.parametrize(
    ("previous", "current"),
    [(TODO, IN_PROGRESS), (BACKLOG, TODO), (IN_PROGRESS, IN_PROGRESS)],
)
def test_moving_between_open_columns_is_not_leaving_done(
    previous: TaskStatusCategory, current: TaskStatusCategory
):
    """Handing a task to review right after finishing your part must not wipe
    the mark you just made."""
    assert left_done(previous, current) is False


@pytest.mark.unit
def test_entering_done_is_not_leaving_it():
    assert left_done(TODO, DONE) is False


@pytest.mark.unit
def test_unknown_previous_category_is_not_leaving_done():
    assert left_done(None, TODO) is False
