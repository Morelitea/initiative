"""Archiving: one pair of endpoints for everything that can be finished with.

Archiving says *this is done, leave it alone*. Everything an initiative offers
can reach that point, and so can a task and an initiative itself, so the set of
things this serves is derived (``ARCHIVE_TARGETS``) rather than listed — a new
tool becomes archivable by joining the ``Tool`` enum.

Which is why this is one polymorphic pair and not ten near-identical routes on
ten routers, the same shape the trash can already uses for restore and purge.

What archiving *does* is one column: ``archived_at``, stamped or cleared. The
consequence is the database's — an archived row and everything under it stops
taking writes (``app.db.frozen``) — so these handlers decide who may ask, and
the rule itself lives in one place rather than in each of them.
"""

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api import resource_access
from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import GuildMessages, InitiativeMessages, ProjectMessages
from app.core.tools import Tool, plural_of
from app.models.platform.user import User
from app.models.tenant._mixins import archive_models
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.task import Task
from app.schemas.tenant.archive import ArchivableType, ArchiveResponse
from app.services import rls as rls_service

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]

#: Wire name -> the model it addresses. Derived from the mixin: the archivable
#: models are the ones carrying ``ArchiveMixin``, and a target's table is its
#: own plural, so neither half is written down twice. A target with no
#: archivable model behind it fails at import rather than at request time.
_BY_TABLE = {model.__tablename__: model for model in archive_models()}
ARCHIVE_REGISTRY: dict[str, type] = {
    target.value: _BY_TABLE[plural_of(target.value)] for target in ArchivableType
}


async def _load(session: RLSSessionDep, entity_type: str, entity_id: int) -> Any:
    """The row, with what the access decision needs already on it.

    Every tool carries ``initiative`` and ``grants``, so one loader serves all
    eight; the two non-tools are loaded for their own checks below. RLS has
    already decided whether the row is visible at all, so a miss here is a 404
    in the ordinary way.
    """
    model = ARCHIVE_REGISTRY[entity_type]
    stmt = select(model).where(model.id == entity_id)
    if entity_type not in {"task", "initiative"}:
        stmt = stmt.options(
            selectinload(model.initiative).selectinload(Initiative.memberships),
            selectinload(model.grants).selectinload(ResourceGrant.role),
        )
    elif entity_type == "task":
        stmt = stmt.options(
            selectinload(Task.project)
            .selectinload(Project.grants)
            .selectinload(ResourceGrant.role),
            selectinload(Task.project)
            .selectinload(Project.initiative)
            .selectinload(Initiative.memberships),
        )
    else:
        stmt = stmt.options(
            selectinload(Initiative.memberships), selectinload(Initiative.roles)
        )
    row = (await session.exec(stmt)).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND[entity_type]
        )
    return row


#: The "no such thing" code per kind — a tool's own, and the two non-tools'.
_NOT_FOUND: dict[str, str] = {
    **{t.value: resource_access.RESOURCE_ACCESS[t].not_found_msg for t in Tool},
    "task": ProjectMessages.NOT_FOUND,
    "initiative": InitiativeMessages.NOT_FOUND,
}


def _authorize(
    entity_type: str,
    row: Any,
    user: User,
    guild_context: GuildContext,
    *,
    unarchiving: bool,
) -> None:
    """Who may put this away, and who may take it back out.

    A tool answers to its own sharing, like any other write to it. A task
    answers to the project it is in. An initiative answers to the guild admins:
    archiving one hides it from every member's sidebar and freezes everything
    inside it, which is a guild-wide act rather than one initiative's.

    ``allow_frozen`` on the way back: unarchiving asks for write on a row that
    is archived by definition.
    """
    if entity_type == "initiative":
        if not rls_service.is_guild_admin(guild_context.role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=GuildMessages.GUILD_ADMIN_REQUIRED,
            )
        return
    governing = Tool.project if entity_type == "task" else Tool(entity_type)
    subject = row.project if entity_type == "task" else row
    resource_access.authorize(
        governing,
        subject,
        user,
        access="write",
        allow_frozen=unarchiving,
    )


@router.post("/archive/{entity_type}/{entity_id}", response_model=ArchiveResponse)
async def archive_entity(
    entity_type: ArchivableType,
    entity_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ArchiveResponse:
    """Mark a thing finished with. Idempotent: an already-archived row keeps
    the stamp it has, so the date means when it was archived, not when it was
    last asked about."""
    row = await _load(session, entity_type.value, entity_id)
    _authorize(entity_type.value, row, current_user, guild_context, unarchiving=False)
    # Read before the commit: committing expires the instance, and reaching for
    # the column afterwards would be a lazy load with no async context to run in.
    stamp = row.archived_at
    if stamp is None:
        stamp = datetime.now(timezone.utc)
        row.archived_at = stamp
        session.add(row)
        await session.commit()
    return ArchiveResponse(
        entity_type=entity_type, entity_id=entity_id, archived_at=stamp
    )


@router.post("/unarchive/{entity_type}/{entity_id}", response_model=ArchiveResponse)
async def unarchive_entity(
    entity_type: ArchivableType,
    entity_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ArchiveResponse:
    """Take it back out. Idempotent on a live row."""
    row = await _load(session, entity_type.value, entity_id)
    _authorize(entity_type.value, row, current_user, guild_context, unarchiving=True)
    if row.archived_at is not None:
        row.archived_at = None
        session.add(row)
        await session.commit()
    return ArchiveResponse(
        entity_type=entity_type, entity_id=entity_id, archived_at=None
    )
