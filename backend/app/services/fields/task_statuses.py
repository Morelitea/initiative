"""The task-status dataset.

A status is a column of somebody's board: a name, a colour, a position, and the
coarse category every project shares. That last one is why this is queryable at
all — a task's own ``status_category`` is a computation rather than a column, so
the way to count work by stage is to join the statuses and group by theirs.
"""

from __future__ import annotations

from app.core.tools import Tool
from app.models.tenant.task import TaskStatus
from app.services.fields.derive import derive_fields
from app.services.fields.spec import Dataset


def build() -> Dataset:
    return Dataset(
        model=TaskStatus,
        # Sharing is the project's, the way a task's is.
        tool=Tool.project,
        name_override="task_statuses",
        fields=derive_fields(TaskStatus),
    )
