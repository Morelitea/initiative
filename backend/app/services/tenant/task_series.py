"""The tasks of one repeating series, and changing one of them alone.

A repeating task makes the next task of its series when it is completed
(``task_creation.advance_recurrence_if_needed``), copied from itself. Every task
the series has made carries ``series_id``, the id of its first task, from the
moment the series first moves on.

An edit asks which tasks it is for:

- **this** — the task keeps the values it changed from in
  ``recurrence_carry``, and the next task is made with those, so the change
  stays on this task;
- **following** — the next task is copied from this one, so the change carries
  forward (what an edit always did);
- **all** — also every other task of the series, completed ones included, for
  the fields the tasks share (:data:`SHARED`).

Nothing here commits.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import joinedload, selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import recurrence
from app.core.user_input_validators import resolve_zone
from app.models.tenant.project import Project
from app.models.tenant.tag import Tag
from app.models.tenant.task import Task, TaskPriority
from app.services.tenant import tags as tags_service
from app.services.tenant import task_checklist as checklist_service
from app.services.tenant import task_description as task_description_service
from app.services.tenant import task_statuses as task_statuses_service
from app.services.tenant.task_completion import sync_completed_at

#: What an edit of just one task keeps from the rest of its series.
CARRIED = (
    "title",
    "description",
    "priority",
    "start_date",
    "due_date",
    "assignee_ids",
    "tag_ids",
)
#: What an edit of every task reaches. Dates, status, checklist and the repeat
#: are each task's own.
SHARED = frozenset({"title", "description", "priority", "assignee_ids", "tag_ids"})
_DATES = frozenset({"start_date", "due_date"})
_TAGS = tags_service.TAG_LINKS["task"]


def _stored(field: str, value: Any) -> Any:
    if field in _DATES:
        return value.isoformat() if value is not None else None
    if field == "priority":
        return TaskPriority(value).value
    if field in {"assignee_ids", "tag_ids"}:
        return sorted(set(value))
    return value


def _loaded(field: str, value: Any) -> Any:
    if field in _DATES:
        return datetime.fromisoformat(value) if value is not None else None
    if field == "priority":
        return TaskPriority(value)
    return value


async def values_of(session: AsyncSession, task: Task) -> dict[str, Any]:
    """The task's :data:`CARRIED` fields as ``recurrence_carry`` holds them."""
    tag_ids = await tags_service.active_tag_ids(session, _TAGS, task.id)
    return {
        "title": task.title,
        "description": task.description,
        "priority": _stored("priority", task.priority),
        "start_date": _stored("start_date", task.start_date),
        "due_date": _stored("due_date", task.due_date),
        "assignee_ids": _stored("assignee_ids", [a.id for a in task.assignees]),
        "tag_ids": _stored("tag_ids", tag_ids),
    }


def values_after(
    task: Task,
    before: dict[str, Any],
    *,
    assignee_ids: list[int] | None,
    tag_ids: list[int] | None,
) -> dict[str, Any]:
    """The task's :data:`CARRIED` fields once an edit that set its columns and
    sent these lists (``None`` = unchanged) has landed."""
    after = {
        field: _stored(field, getattr(task, field))
        for field in ("title", "description", "priority", "start_date", "due_date")
    }
    after["assignee_ids"] = (
        before["assignee_ids"]
        if assignee_ids is None
        else _stored("assignee_ids", assignee_ids)
    )
    after["tag_ids"] = (
        before["tag_ids"] if tag_ids is None else _stored("tag_ids", tag_ids)
    )
    return after


def changed(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    return {field for field in CARRIED if before[field] != after[field]}


def keep(task: Task, before: dict[str, Any], after: dict[str, Any]) -> None:
    """An edit of just this task: remember what each field changed from. A
    field set back to the series' value no longer needs remembering."""
    carry = dict(task.recurrence_carry or {})
    for field in changed(before, after):
        carry.setdefault(field, before[field])
        if carry[field] == after[field]:
            del carry[field]
    task.recurrence_carry = carry or None


def release(task: Task, fields: set[str]) -> None:
    """These fields carry forward again, as this task now has them."""
    carry = {
        field: value
        for field, value in (task.recurrence_carry or {}).items()
        if field not in fields
    }
    task.recurrence_carry = carry or None


def carried(task: Task) -> dict[str, Any]:
    """What the next task of the series is made with in place of this task's
    own values."""
    return {
        field: _loaded(field, value)
        for field, value in (task.recurrence_carry or {}).items()
    }


def next_dates(
    task: Task, *, now: datetime, user_timezone: str | None
) -> tuple[datetime | None, datetime] | None:
    """The next task's start and due dates, or ``None`` when the series has no
    more. Raises ``ValueError`` for a rule that does not parse."""
    rule = recurrence.parse(task.recurrence).rule
    values = carried(task)
    due = values.get("due_date", task.due_date)
    start = values.get("start_date", task.start_date)
    if (task.recurrence_strategy or "fixed") == "rolling":
        # Rolling counts from the completer's local day, at the task's own
        # local time of day: a 5pm LA task is midnight UTC the next day, so a
        # UTC day would land a day early. The zone is the request's, read here
        # and never stored.
        zone = resolve_zone(user_timezone)
        due_local = due.astimezone(zone)
        base = (
            now.astimezone(zone)
            .replace(
                hour=due_local.hour,
                minute=due_local.minute,
                second=due_local.second,
                microsecond=due_local.microsecond,
            )
            .astimezone(zone)
        )
    else:
        base = due
    # The task's own counter ends a COUNT series: every successor is a new row
    # whose start moves, so dateutil would count from the wrong place.
    count = rule.get("COUNT", [None])[0]
    if count is not None and task.recurrence_occurrence_count + 1 >= count:
        return None
    next_due = recurrence.next_start(
        task.recurrence, base, task.recurrence_shift, count=False
    )
    if next_due is None:
        return None
    length: timedelta | None = due - start if start and due else None
    return (next_due - length if length else None), next_due


async def retag(session: AsyncSession, task_id: int, tag_ids: list[int]) -> None:
    """Give the task these tags, leaving out any trashed since."""
    live = (await session.exec(select(Tag.id).where(Tag.id.in_(tag_ids)))).all()
    await tags_service.replace_entity_tags(session, _TAGS, task_id, sorted(live))


async def skip(
    session: AsyncSession, task: Task, *, now: datetime, user_timezone: str | None
) -> bool:
    """Move the task on to the next occurrence without completing it, as the
    next task would have been made. False when the series has no more."""
    from app.services.tenant.task_creation import set_task_assignees

    if task.due_date is None:
        return False
    try:
        dates = next_dates(task, now=now, user_timezone=user_timezone)
    except ValueError:
        return False
    if dates is None:
        return False
    values = carried(task)
    for field in ("title", "description", "priority"):
        if field in values:
            setattr(task, field, values[field])
    if "assignee_ids" in values:
        project = await session.get(Project, task.project_id)
        if project is None:  # the task was just read inside it
            raise RuntimeError("a repeating task's project is gone")
        await set_task_assignees(
            session, task, values["assignee_ids"], project=project, carried=True
        )
    if "tag_ids" in values:
        await retag(session, task.id, values["tag_ids"])
    if "description" in values:
        await task_description_service.record_references(
            session, task, author_id=task.created_by
        )
    default_status = await task_statuses_service.get_default_status(
        session, task.project_id
    )
    task.task_status_id = default_status.id  # ty: ignore[invalid-assignment] — persisted row, id is set
    task.task_status = default_status
    sync_completed_at(task, default_status.category, now=now)
    task.start_date, task.due_date = dates
    task.recurrence_occurrence_count += 1
    task.checklist = checklist_service.cloned(task.checklist)
    task.recurrence_carry = None
    task.series_id = task.series_id or task.id
    task.updated_at = now
    return True


async def others(session: AsyncSession, task: Task) -> list[Task]:
    """Every other live task of the task's series, with its project."""
    if task.series_id is None:
        return []
    statement = (
        select(Task)
        .where(Task.series_id == task.series_id, Task.id != task.id)
        .options(
            joinedload(Task.project).joinedload(Project.initiative),
            selectinload(Task.assignees),
        )
    )
    return list((await session.exec(statement)).all())


async def apply_to_others(
    session: AsyncSession,
    members: list[Task],
    after: dict[str, Any],
    fields: set[str],
    *,
    now: datetime,
    author_id: int | None,
) -> None:
    """Give every other task of the series the task's new :data:`SHARED`
    values. The caller has checked it may change each one."""
    from app.services.tenant.task_creation import set_task_assignees

    fields = fields & SHARED
    if not fields:
        return
    for member in members:
        for field in fields - {"assignee_ids", "tag_ids"}:
            setattr(member, field, _loaded(field, after[field]))
        if "assignee_ids" in fields:
            await set_task_assignees(
                session,
                member,
                after["assignee_ids"],
                project=member.project,
                carried=True,
            )
        if "tag_ids" in fields:
            await tags_service.replace_entity_tags(
                session, _TAGS, member.id, after["tag_ids"]
            )
        if "description" in fields:
            await task_description_service.record_references(
                session, member, author_id=author_id
            )
        release(member, fields)
        member.updated_at = now
