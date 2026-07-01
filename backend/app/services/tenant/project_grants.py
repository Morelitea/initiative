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
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ProjectMessages
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.task import Task, TaskAssignee
from app.services import permissions as permissions_service


async def get_project(session: AsyncSession, project_id: int) -> Project | None:
    """Load a project with just the relationships the grant flow needs — its
    ``grants`` (for authorization + owner resolution) and ``initiative.memberships``
    (for the write-holder diff). RLS scopes the row to the request's guild."""
    stmt = (
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.grants).selectinload(ResourceGrant.role),
            selectinload(Project.initiative).selectinload(Initiative.memberships),
        )
    )
    return (await session.exec(stmt)).one_or_none()


def ensure_grantable(project: Project) -> None:
    """Sharing can't be changed on an archived project (mirrors the other
    write paths that reject archived projects)."""
    if project.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ProjectMessages.IS_ARCHIVED
        )


def write_holder_ids(project: Project) -> set[int]:
    """Initiative-member user IDs with effective write+ (write/owner) access to the
    project — i.e. those eligible to be task assignees. Pure read of the
    eager-loaded ``grants`` + ``initiative.memberships`` (no DB I/O)."""
    resource = permissions_service.DAC_RESOURCES["project"]
    memberships = getattr(project.initiative, "memberships", None) or []
    return {
        m.user_id
        for m in memberships
        if m.user_id is not None
        and permissions_service.effective_level(resource, project, m.user_id)
        in ("write", "owner")
    }


async def remove_user_task_assignments(
    session: Any, project_id: int, user_ids: set[int]
) -> None:
    """Unassign the given users from every task in the project. Called when a grant
    change drops a user below write access, since a user cannot be assigned to
    tasks they can no longer edit."""
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
