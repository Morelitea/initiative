"""Put a task row in a project — the part every creator shares.

Creating a task has an endpoint-shaped half (who is allowed to, which
assignees to notify, which tags and properties to attach) and a row-shaped
half: find the end of the list, make sure the project has its statuses, decide
which status the task starts in, and build the row. This module is the second
half, so the three callers that need it — the task endpoint, the recurrence
roll-forward, and the intake writer — resolve a status the same way.

It flushes and does not commit, so a caller can compose it into a larger
transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import TaskMessages
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskStatus
from app.services.tenant import filter_presets as filter_presets_service
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
