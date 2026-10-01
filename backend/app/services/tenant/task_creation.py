"""Put a task row in a project, and name who works on it.

Creating a task has an endpoint-shaped half (who is allowed to, which
assignees to notify, which tags and properties to attach) and a row-shaped
half: find the end of the list, make sure the project has its statuses, decide
which status the task starts in, and build the row. This module is the second
half, shared by the task endpoint and the intake writer, together with the
pieces every task change reaches for: replacing a task's assignees, rolling a
recurring task forward to its next occurrence when it is completed (from the
task routes and from a status change that moves tasks between columns), and
copying a project's tasks into a copy of it (``copy_tasks``).

Nothing here commits, so a caller can compose it into a larger transaction.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import recurrence
from app.core.messages import TaskMessages
from app.core.relationships import (
    DERIVED_TYPES,
    Provenance,
    RelationshipType,
    node_id,
)
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db.session import require_actor_context
from app.models.tenant.project import Project
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory
from app.services import notifications as notifications_service
from app.services.tenant import content_references, relationships
from app.services.tenant import filter_presets as filter_presets_service
from app.services.tenant import named_people
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant import task_checklist as checklist_service
from app.services.tenant import task_completion
from app.services.tenant import task_description as task_description_service
from app.services.tenant import task_series
from app.services.tenant import task_statuses as task_statuses_service
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
        dates = task_series.next_dates(task, now=now, user_timezone=user_timezone)
    except ValueError:
        return False
    if dates is None:
        task.recurrence = None
        return False
    new_start, next_due = dates

    # An edit of just this task leaves the next one with what it changed from.
    values = task_series.carried(task)
    task.series_id = task.series_id or task.id
    default_status = await task_statuses_service.get_default_status(
        session, task.project_id
    )
    new_task = Task(
        project_id=task.project_id,
        task_status_id=default_status.id,
        title=values.get("title", task.title),
        description=values.get("description", task.description),
        priority=values.get("priority", task.priority),
        start_date=new_start,
        due_date=next_due,
        recurrence=task.recurrence,
        recurrence_shift=task.recurrence_shift,
        recurrence_strategy=task.recurrence_strategy or "fixed",
        position=await next_position(session, task.project_id),
        recurrence_occurrence_count=task.recurrence_occurrence_count + 1,
        series_id=task.series_id,
        created_by=task.created_by,
        checklist=checklist_service.cloned(task.checklist),
    )
    sync_completed_at(new_task, default_status.category, now=now)
    session.add(new_task)
    await session.flush()
    assignee_ids = values.get(
        "assignee_ids", [assignee.id for assignee in task.assignees]
    )
    project = await session.get(Project, task.project_id)
    if project is None:  # the task was just read inside it
        raise RuntimeError("a recurring task's project is gone")
    await set_task_assignees(
        session, new_task, assignee_ids, project=project, carried=True
    )
    if "tag_ids" in values:
        await task_series.retag(session, new_task.id, values["tag_ids"])
    else:
        await tags_service.copy_entity_tags(
            session,
            tags_service.TAG_LINKS["task"],
            {task.id: new_task.id},
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
    await properties_service.annotate_properties(session, [new_task])

    task.recurrence = None
    task.recurrence_strategy = "fixed"
    task.recurrence_carry = None
    task.updated_at = now
    session.add(task)
    return True


def _date_shift(
    template: Project,
    new_project: Project,
    template_tasks: list[Task],
) -> timedelta | None:
    """Offset to move template task dates onto the new project's schedule.

    Task dates in a template are relative: a task due three weeks after the
    template's start should land three weeks after the new project's start.
    Anchors on the projects' start dates when the new project has one,
    otherwise on their end dates. A template without an explicit start/end
    falls back to its earliest/latest task date. Returns None when there is
    nothing to anchor on, in which case dates are copied as-is.
    """
    task_dates = [
        value.date()
        for task in template_tasks
        for value in (task.start_date, task.due_date)
        if value is not None
    ]
    if new_project.start_date is not None:
        anchor = template.start_date or (min(task_dates) if task_dates else None)
        if anchor is not None:
            return new_project.start_date - anchor
    if new_project.end_date is not None:
        anchor = template.end_date or (max(task_dates) if task_dates else None)
        if anchor is not None:
            return new_project.end_date - anchor
    return None


async def copy_tasks(
    session: AsyncSession,
    template: Project,
    new_project: Project,
    *,
    status_mapping: dict[int, int],
    fallback_status_ids: dict[TaskStatusCategory, int],
) -> list[Task]:
    """Copy ``template``'s tasks into ``new_project``, a copy of it whose
    statuses ``status_mapping`` maps; returns the copies. Dates move onto the
    new project's schedule (:func:`_date_shift`)."""
    task_stmt = (
        select(Task)
        .options(
            selectinload(Task.assignees),
            selectinload(Task.task_status),
        )
        .where(Task.project_id == template.id)
        .order_by(Task.position.asc(), Task.id.asc())
    )
    task_result = await session.exec(task_stmt)
    template_tasks = task_result.all()
    if not template_tasks:
        return []

    now = datetime.now(timezone.utc)
    categories = await task_completion.status_categories(session, new_project.id)
    date_shift = _date_shift(template, new_project, list(template_tasks))
    copies: list[tuple[Task, Task]] = []
    for template_task in template_tasks:
        template_status_id = getattr(template_task, "task_status_id", None)
        mapped_status_id = None
        if template_status_id is not None:
            mapped_status_id = status_mapping.get(template_status_id)
        if mapped_status_id is None:
            category = getattr(
                getattr(template_task, "task_status", None), "category", None
            )
            if category is not None:
                mapped_status_id = fallback_status_ids.get(category)
        if mapped_status_id is None and fallback_status_ids:
            mapped_status_id = next(iter(fallback_status_ids.values()))
        start_date = template_task.start_date
        due_date = template_task.due_date
        repeat = template_task.recurrence
        if date_shift is not None:
            if start_date is not None:
                start_date = start_date + date_shift
            if due_date is not None:
                due_date = due_date + date_shift
            if repeat is not None:
                repeat = recurrence.moved(repeat, date_shift)
        new_task = Task(
            project_id=new_project.id,
            title=template_task.title,
            description=template_task.description,
            task_status_id=mapped_status_id,
            priority=template_task.priority,
            start_date=start_date,
            due_date=due_date,
            recurrence=repeat,
            recurrence_shift=template_task.recurrence_shift,
            recurrence_strategy=template_task.recurrence_strategy,
            position=template_task.position,
            checklist=checklist_service.cloned(template_task.checklist, keep_done=True),
        )
        task_completion.sync_completed_at(
            new_task, categories.get(mapped_status_id), now=now
        )
        session.add(new_task)
        copies.append((template_task, new_task))
    await session.flush()

    # Assignees come along only where they can open the new project.
    can_open = await named_people.readers(
        session,
        named_people.Governing.of(Tool.project, new_project),
        {assignee.id for task, _ in copies for assignee in task.assignees},
    )
    for template_task, new_task in copies:
        session.add_all(
            TaskAssignee(task_id=new_task.id, user_id=assignee.id)
            for assignee in template_task.assignees
            if assignee.id in can_open
        )
        if new_task.description:
            await task_description_service.record_references(
                session, new_task, author_id=None
            )
    copied_ids = {
        s.id: c.id for s, c in copies if s.id is not None and c.id is not None
    }
    await tags_service.copy_entity_tags(
        session, tags_service.TAG_LINKS["task"], copied_ids
    )
    await _copy_relationships(session, copied_ids)
    return [task for _, task in copies]


#: Edge types a task copy does not carry. Tags travel through
#: ``copy_entity_tags``, and a derived edge is read out of a body on save
#: rather than asserted, so neither is copied here.
_UNCOPIED_RELATIONSHIP_TYPES = frozenset({RelationshipType.tagged_with}) | DERIVED_TYPES


async def _copy_relationships(
    session: AsyncSession, task_mapping: dict[int, int]
) -> None:
    """Carry the source tasks' relations onto their copies.

    Every live edge touching a source task is re-created on the copy. An end
    that is itself a source task is remapped to its copy, so a dependency
    between two template tasks becomes a dependency between the two new tasks;
    any other end (a document, a task outside the template) is kept as-is.

    Each copy is a link made on the creator's behalf, so it goes through
    ``relationships.link_many`` like any other, and one it refuses is left behind:
    a far end the creator cannot open, one in another initiative than the new
    project, an archived one, or a source they cannot edit.
    """
    if not task_mapping or not content_references.records_edges(session):
        return
    source_nodes = [node_id(SearchEntityType.task, task_id) for task_id in task_mapping]
    live = EntityRelationship.removed_at.is_(None)  # type: ignore[union-attr]
    outbound = await session.exec(
        select(EntityRelationship).where(
            EntityRelationship.source_node.in_(source_nodes),  # type: ignore[union-attr]
            live,
        )
    )
    inbound = await session.exec(
        select(EntityRelationship).where(
            EntityRelationship.target_node.in_(source_nodes),  # type: ignore[union-attr]
            live,
        )
    )
    edges: dict[int, EntityRelationship] = {}
    for row in [*outbound.all(), *inbound.all()]:
        if row.id is not None:
            edges[row.id] = row

    def remapped(kind: str, entity_id: int) -> relationships.Endpoint:
        entity_kind = SearchEntityType(kind)
        if entity_kind is SearchEntityType.task:
            entity_id = task_mapping.get(entity_id, entity_id)
        return relationships.Endpoint(entity_kind, entity_id)

    await relationships.link_many(
        session,
        [
            relationships.Link(
                source=remapped(row.source_type, row.source_id),
                relationship_type=RelationshipType(row.relationship_type),
                target=remapped(row.target_type, row.target_id),
                provenance=Provenance(row.provenance),
                confidence=row.confidence,
            )
            for row in sorted(edges.values(), key=lambda r: (r.created_at, r.id or 0))
            if RelationshipType(row.relationship_type)
            not in _UNCOPIED_RELATIONSHIP_TYPES
        ],
        user_id=require_actor_context(session).user_id,
    )
