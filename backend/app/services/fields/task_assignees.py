"""The assignment dataset — which task is whose.

A task's assignees are a table of their own, so who is doing something is a
join rather than a column. That is what makes counting work by person possible
at all: tasks to assignments to :mod:`members`, three relations, inside the
ceiling a statement is held to.

Nothing else about it is interesting. It carries the two ids it relates and no
state, and its rows are reached exactly where the tasks they belong to are.
"""

from __future__ import annotations

from app.core.tools import Tool
from app.models.tenant.task import TaskAssignee
from app.services.fields.derive import derive_fields
from app.services.fields.spec import Dataset


def build() -> Dataset:
    return Dataset(
        model=TaskAssignee,
        # Sharing is the project's, the way a task's is — an assignment is
        # reached by whoever reaches the task it is on.
        tool=Tool.project,
        name_override="task_assignees",
        fields=derive_fields(TaskAssignee),
    )
