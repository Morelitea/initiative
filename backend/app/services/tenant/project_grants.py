"""Project-specific bits of the generic grant flow.

A grant loader (just enough eager-loading for the authorization engine + the
write-holder diff) and the project-only side effect: when a sharing change drops
a member below write access they must be unassigned from the project's tasks
(you can't be assigned to tasks you can no longer edit). Kept in the service
layer so both the per-project grant endpoint and the generic
``resource_access.set_resource_grants`` path share one implementation (and to
avoid an endpoint↔resource_access import cycle).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ProjectMessages
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.task import Task, TaskAssignee


async def get_project(session: AsyncSession, project_id: int) -> Project | None:
    """Load a project with just what the grant flow needs — its ``grants``
    (owner resolution) and the level the request holds on it. RLS scopes the
    row to the request's guild."""
    stmt = (
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.grants).selectinload(ResourceGrant.role),
            selectinload(Project.initiative),
            undefer(Project.actions),
        )
    )
    return (await session.exec(stmt)).one_or_none()


async def get_project_hydrated(
    session: AsyncSession, project_id: int, *, populate_existing: bool = False
) -> Project | None:
    """Load a project with everything a serialized ``ProjectRead`` reads.

    The grant loader above carries what the access decision needs; this carries
    that plus what the response does — the grant holders by name and the
    project's task statuses. RLS scopes the row to the request's guild.

    ``populate_existing=True`` refreshes a project already in the session's
    identity map, for a re-read after a commit (``expire_on_commit=False``
    otherwise keeps the collections as they were before the write).
    """
    stmt = (
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.grants).options(
                selectinload(ResourceGrant.role), selectinload(ResourceGrant.user)
            ),
            selectinload(Project.initiative),
            undefer(Project.actions),
            selectinload(Project.task_statuses),
        )
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    return (await session.exec(stmt)).one_or_none()


def ensure_grantable(project: Project) -> None:
    """Sharing can't be changed on an archived project (mirrors the other
    write paths that reject archived projects)."""
    if project.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ProjectMessages.IS_ARCHIVED
        )


async def remove_user_task_assignments(
    session: Any, project_id: int, user_ids: set[int]
) -> None:
    """Unassign the given users from every task in the project. Called when a grant
    change leaves them unable to open it, since only people who can are named on
    its tasks."""
    if not user_ids:
        return
    task_ids = (
        await session.exec(select(Task.id).where(Task.project_id == project_id))
    ).all()
    if not task_ids:
        return
    await session.exec(
        sa_delete(TaskAssignee).where(
            TaskAssignee.task_id.in_(task_ids),
            TaskAssignee.user_id.in_(list(user_ids)),
        )
    )
