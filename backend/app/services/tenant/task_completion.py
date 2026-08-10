"""Track who has finished their part of a task.

Completion is per **assignment**, not per task. Someone can be done with their
share of the work while the task itself lives on — handed to review, or waiting
on a co-assignee — so ``TaskAssignee.completed_at`` records when *that person*
finished, and the task's status keeps recording where the work as a whole
stands. The two answer different questions and neither derives from the other.

Three rules keep the column honest, all of them owned here:

* a task reaching a done status finishes every **assignee's** part
  (:func:`complete_all_assignments`). Only assignees have a completion at all —
  it lives on the assignment row — but the person who moved the task need not
  be one of them. Anyone already marked keeps their original time: they
  finished when they finished, not when the task closed.
* a task leaving a done status erases every part
  (:func:`reopen_all_assignments`). Reopened work is nobody's finished work.
* between those, a person marks their own part done or not
  (:func:`set_assignment_completed`), and nothing else disturbs it — so
  finishing your share and then handing the task to review keeps the mark.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.task import TaskAssignee, TaskStatusCategory


def left_done(
    previous: Optional[TaskStatusCategory],
    current: Optional[TaskStatusCategory],
) -> bool:
    """Whether a status change took the task back out of a done column."""
    return previous == TaskStatusCategory.done and current != TaskStatusCategory.done


async def complete_all_assignments(
    session: AsyncSession, *, task_id: int, now: datetime
) -> None:
    """Mark every outstanding assignment on a finished task as done.

    If the work is over then so is everyone's part of it. Assignments already
    marked keep their original time — someone who finished on Tuesday did not
    finish again when the task closed on Thursday.
    """
    await session.exec(
        update(TaskAssignee)
        .where(TaskAssignee.task_id == task_id, TaskAssignee.completed_at.is_(None))
        .values(completed_at=now)
    )


async def reopen_all_assignments(session: AsyncSession, *, task_id: int) -> None:
    """Clear every assignment's completion because the task is open again.

    Everyone's, not just the mover's: work pulled back out of a done column is
    live for whoever is on it, and leaving someone marked done would hide it
    from the one list meant to surface it.
    """
    await session.exec(
        update(TaskAssignee)
        .where(TaskAssignee.task_id == task_id, TaskAssignee.completed_at.is_not(None))
        .values(completed_at=None)
    )


async def sync_assignments_for_status_change(
    session: AsyncSession,
    *,
    task_id: int,
    previous: Optional[TaskStatusCategory],
    current: Optional[TaskStatusCategory],
    now: datetime,
) -> None:
    """Apply the two task-driven rules after a task's status moves.

    The single seam for every path that reassigns ``task_status_id``, so the
    rules live in one place instead of at each call site.
    """
    if current == TaskStatusCategory.done:
        await complete_all_assignments(session, task_id=task_id, now=now)
    elif left_done(previous, current):
        await reopen_all_assignments(session, task_id=task_id)


async def sync_assignments_for_recategorised_status(
    session: AsyncSession,
    *,
    status_id: int,
    previous: Optional[TaskStatusCategory],
    current: TaskStatusCategory,
    now: datetime,
) -> None:
    """Apply the same rules to every task sitting in a recategorised column.

    Editing a status moves its whole column across the done boundary without
    touching a single task row, so the assignments are realigned in one
    statement rather than task by task.
    """
    from app.models.tenant.task import Task

    tasks_in_status = select(Task.id).where(Task.task_status_id == status_id)

    if current == TaskStatusCategory.done:
        await session.exec(
            update(TaskAssignee)
            .where(
                TaskAssignee.task_id.in_(tasks_in_status),
                TaskAssignee.completed_at.is_(None),
            )
            .values(completed_at=now)
        )
    elif left_done(previous, current):
        await session.exec(
            update(TaskAssignee)
            .where(
                TaskAssignee.task_id.in_(tasks_in_status),
                TaskAssignee.completed_at.is_not(None),
            )
            .values(completed_at=None)
        )


async def set_assignment_completed(
    session: AsyncSession,
    *,
    task_id: int,
    user_id: int,
    completed: bool,
    now: datetime,
) -> Optional[TaskAssignee]:
    """Mark one person's part done or not done.

    Returns the assignment, or ``None`` if the user is not assigned — the
    caller turns that into a 404 rather than silently doing nothing. Re-marking
    an already-complete assignment keeps its original timestamp.
    """
    assignment = (
        await session.exec(
            select(TaskAssignee).where(
                TaskAssignee.task_id == task_id,
                TaskAssignee.user_id == user_id,
            )
        )
    ).first()
    if assignment is None:
        return None

    if completed:
        if assignment.completed_at is None:
            assignment.completed_at = now
    else:
        assignment.completed_at = None
    session.add(assignment)
    return assignment


async def outstanding_assignee_count(session: AsyncSession, *, task_id: int) -> int:
    """How many assignees have not yet marked their part done."""
    from sqlalchemy import func

    return (
        await session.exec(
            select(func.count())
            .select_from(TaskAssignee)
            .where(
                TaskAssignee.task_id == task_id,
                TaskAssignee.completed_at.is_(None),
            )
        )
    ).one()
