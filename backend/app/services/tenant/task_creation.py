"""Put a task row in a project, and name who works on it.

Creating a task has an endpoint-shaped half (who is allowed to, which
assignees to notify, which tags and properties to attach) and a row-shaped
half: find the end of the list, make sure the project has its statuses, decide
which status the task starts in, and build the row. This module is the second
half, shared by the task endpoint and the intake writer, together with the two
pieces every task change reaches for: replacing a task's assignees, and rolling
a recurring task forward to its next occurrence when it is completed (from the
task routes and from a status change that moves tasks between columns).

Nothing here commits, so a caller can compose it into a larger transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status as http_status
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import TaskMessages
from app.core.tools import Tool
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory
from app.schemas.tenant.task import TaskRecurrence
from app.services import notifications as notifications_service
from app.services.tenant import filter_presets as filter_presets_service
from app.services.tenant import named_people
from app.services.tenant import tags as tags_service
from app.services.tenant import task_checklist as checklist_service
from app.services.tenant import task_description as task_description_service
from app.services.tenant import task_statuses as task_statuses_service
from app.services.tenant.recurrence import get_next_due_date
from app.services.tenant.task_completion import sync_completed_at


async def next_position(session: AsyncSession, project_id: int) -> float:
    """The position that puts a new task at the end of the project."""
    result = await session.exec(
        select(func.max(Task.position)).where(Task.project_id == project_id)
    )
    return (result.one_or_none() or 0) + 1


async def resolve_start_status(
    session: AsyncSession,
    *,
    project_id: int,
    task_status_id: Optional[int] = None,
) -> TaskStatus:
    """The status a new task starts in, seeding the project's defaults first.

    A named status must belong to this project; anything else is a 400 rather
    than a silent fall back to the default, so a caller naming another
    project's status learns it instead of filing into the wrong column.

    Seeding here is the same safety net the endpoint has always had: the read
    path deliberately never seeds — a read-only grantee routes into a
    SELECT-only role and could not — so the first write is where a project that
    somehow arrived without its defaults gets them.
    """
    await task_statuses_service.ensure_default_statuses(session, project_id)
    await filter_presets_service.ensure_default_presets(session, project_id)

    if task_status_id is not None:
        selected = await task_statuses_service.get_project_status(
            session, status_id=task_status_id, project_id=project_id
        )
        if selected is None:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=TaskMessages.STATUS_NOT_FOUND,
            )
        return selected

    return await task_statuses_service.get_default_status(session, project_id)


async def create_task_row(
    session: AsyncSession,
    *,
    project: Project,
    task_status_id: Optional[int] = None,
    now: Optional[datetime] = None,
    **fields: Any,
) -> Task:
    """Build, add and flush one task at the end of ``project``.

    ``fields`` are the task's own columns — title, description, priority, due
    date and the rest; the caller owns validating them. Assignees, tags and
    property values are attached by the caller afterwards, because each is a
    service of its own with its own failure modes.

    The caller is responsible for access control: this writes the row it is
    asked for.
    """
    selected_status = await resolve_start_status(
        session, project_id=project.id, task_status_id=task_status_id
    )
    task = Task(
        **fields,
        project_id=project.id,
        position=await next_position(session, project.id),
        task_status_id=selected_status.id,
    )
    sync_completed_at(
        task, selected_status.category, now=now or datetime.now(timezone.utc)
    )
    session.add(task)
    await session.flush()
    return task


async def set_task_assignees(
    session: AsyncSession,
    task: Task,
    assignee_ids: list[int] | None,
    *,
    project: Project,
    carried: bool = False,
) -> None:
    """Replace the task's assignees. Everyone named must be able to open the
    project; ``carried`` is a copy made from existing assignees (a duplicate, a
    recurrence, a move), which keeps those who still can rather than refusing."""
    unique_ids = list(dict.fromkeys(assignee_ids or []))
    governing = named_people.Governing.of(Tool.project, project)
    if carried:
        keep = await named_people.readers(session, governing, unique_ids)
        unique_ids = [user_id for user_id in unique_ids if user_id in keep]
    else:
        await named_people.require_readers(session, governing, unique_ids)

    # Read the current set before replacing it, so anyone dropped can have
    # their un-sent digest item withdrawn. An explicit query rather than
    # ``task.assignees`` — on a freshly flushed task that relationship is not
    # loaded yet, and touching it would fire a lazy load.
    previous_ids = set(
        (
            await session.exec(
                select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id)
            )
        ).all()
    )

    delete_stmt = delete(TaskAssignee).where(TaskAssignee.task_id == task.id)
    await session.exec(delete_stmt)

    if unique_ids:
        session.add_all(
            [TaskAssignee(task_id=task.id, user_id=user_id) for user_id in unique_ids]
        )

    await notifications_service.dequeue_task_assignment_events(
        session, task_id=task.id, user_ids=sorted(previous_ids - set(unique_ids))
    )

    await session.flush()
    await session.refresh(task, attribute_names=["assignees"])


def _resolve_user_zone(user_tz: str | None) -> ZoneInfo:
    """Resolve a user's stored ``timezone`` string to a ``ZoneInfo``,
    falling back to UTC if the value is missing or unrecognised.

    The user model defaults to ``"UTC"`` so this is mostly a guard
    against bad data — but we treat an unknown zone as UTC rather than
    erroring, since recurrence-on-completion shouldn't fail just
    because a profile field drifted.
    """
    if not user_tz:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(user_tz)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


async def advance_recurrence_if_needed(
    session: AsyncSession,
    task: Task,
    *,
    previous_status_category: TaskStatusCategory | None,
    now: datetime,
    user_timezone: str | None,
) -> bool:
    current_category = task.task_status.category if task.task_status else None
    if (
        previous_status_category == TaskStatusCategory.done
        or current_category != TaskStatusCategory.done
        or not task.recurrence
        or task.due_date is None
    ):
        return False

    try:
        recurrence = TaskRecurrence.model_validate(task.recurrence)
    except ValidationError:
        return False

    strategy = task.recurrence_strategy or "fixed"
    if strategy == "rolling":
        # For rolling: use the user's local *calendar day* of completion
        # but preserve the task's original *local* time-of-day. Doing
        # this math in UTC produced an off-by-one when the task's
        # local time crossed UTC midnight: e.g. a 5pm LA task is
        # midnight UTC the next day, so a UTC-anchored
        # ``now.replace(hour=0)`` landed the new occurrence one local
        # day earlier than the user's "complete + 3 days" intuition.
        zone = _resolve_user_zone(user_timezone)
        now_local = now.astimezone(zone)
        due_local = task.due_date.astimezone(zone)
        # ``replace()`` doesn't consult the zone's transition table on
        # its own, so a gap-time result (e.g. 2:30 AM on a spring-
        # forward day) is left labelled with the surrounding offset.
        # The trailing ``astimezone(zone)`` is defensive — when the
        # source and target tzinfo are the same ZoneInfo instance
        # CPython short-circuits to ``return self``, so this is a
        # no-op in that case, but it documents the intent and makes
        # the call site safe if a future change resolves ``zone``
        # from a different cache. The downstream ``+ timedelta``
        # advance preserves wall-clock time across DST, which is the
        # behaviour we want for daily recurrence: an "every day at
        # 2:30 AM" task continues to fire at 2:30 AM after DST kicks
        # in, the same way an alarm clock would.
        base_local = now_local.replace(
            hour=due_local.hour,
            minute=due_local.minute,
            second=due_local.second,
            microsecond=due_local.microsecond,
        ).astimezone(zone)
        # ``get_next_due_date`` is timezone-naive about its frequency
        # math (adds ``timedelta(days=...)`` directly), so keep the
        # base in local time for the duration of the calculation and
        # let the caller convert back to UTC if needed. Storing a
        # timezone-aware value preserves the right instant either way.
        base_date = base_local
    else:
        base_date = task.due_date
    next_due = get_next_due_date(
        base_date,
        recurrence,
        completed_occurrences=task.recurrence_occurrence_count,
    )
    if next_due is None:
        task.recurrence = None
        return False

    duration = None
    if task.start_date and task.due_date:
        duration = task.due_date - task.start_date
    new_start = next_due - duration if duration else None

    default_status = await task_statuses_service.get_default_status(
        session, task.project_id
    )
    new_task = Task(
        project_id=task.project_id,
        task_status_id=default_status.id,
        title=task.title,
        description=task.description,
        priority=task.priority,
        start_date=new_start,
        due_date=next_due,
        recurrence=recurrence.model_dump(mode="json"),
        recurrence_strategy=strategy,
        position=await next_position(session, task.project_id),
        recurrence_occurrence_count=task.recurrence_occurrence_count + 1,
        created_by=task.created_by,
        checklist=checklist_service.cloned(task.checklist),
    )
    sync_completed_at(new_task, default_status.category, now=now)
    session.add(new_task)
    await session.flush()
    assignee_ids = [assignee.id for assignee in task.assignees]
    project = await session.get(Project, task.project_id)
    if project is None:  # the task was just read inside it
        raise RuntimeError("a recurring task's project is gone")
    await set_task_assignees(
        session, new_task, assignee_ids, project=project, carried=True
    )
    await tags_service.copy_entity_tags(
        session,
        tags_service.TAG_LINKS["task"],
        source_id=task.id,
        target_id=new_task.id,
    )
    if new_task.description:
        await task_description_service.record_references(
            session, new_task, author_id=task.created_by
        )
    await session.flush()
    # Reload through a select rather than ``session.refresh``: refresh takes no
    # loader options, so the assignees would come back unloaded and the
    # serializer would have to emit IO from sync context. ``populate_existing``
    # applies the freshly loaded rows to the identity-mapped instance.
    await session.exec(
        select(Task)
        .where(Task.id == new_task.id)
        .options(
            selectinload(Task.assignees),
        )
        .execution_options(populate_existing=True)
    )
    await tags_service.annotate_tags(session, [new_task])

    task.recurrence = None
    task.recurrence_strategy = "fixed"
    task.updated_at = now
    session.add(task)
    return True
