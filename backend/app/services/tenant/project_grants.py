"""The project loaders the generic resource-access registry uses.

A grant loader (just enough eager-loading for the authorization engine + the
write-holder diff) and the hydrated loader a serialized ``ProjectRead`` reads.
Kept in the service layer so the project endpoints and
``resource_access`` share one implementation (and to avoid an
endpoint↔resource_access import cycle).
"""

from __future__ import annotations

from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceGrant


async def get_project(session: AsyncSession, project_id: int) -> Project | None:
    """Load a project with just what the grant flow needs — its ``grants``
    (owner resolution) and the level the request holds on it. RLS scopes the
    row to the request's guild."""
    stmt = (
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.grants),
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
            selectinload(Project.grants).selectinload(ResourceGrant.user),
            selectinload(Project.initiative),
            undefer(Project.actions),
            selectinload(Project.task_statuses),
        )
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    return (await session.exec(stmt)).one_or_none()
