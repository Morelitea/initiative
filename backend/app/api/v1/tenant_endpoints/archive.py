"""Archiving: one pair of endpoints for everything that can be finished with.

Archiving says *this is done, leave it alone*. Everything an initiative offers
can reach that point, and so can a task and an initiative itself, so the set of
things this serves is derived (``ARCHIVE_TARGETS``) rather than listed — a new
tool becomes archivable by joining the ``Tool`` enum.

Which is why this is one polymorphic pair and not ten near-identical routes on
ten routers, the same shape the trash can already uses for restore and purge.

What archiving *does* is one column, ``archived_at``, on the thing named and on
everything inside it — see ``services.tenant.archive`` for the cascade. The
consequence is the database's: an archived row and everything under it stops
taking writes (``app.db.frozen``). So these handlers decide who may ask, and
both rules live in one place rather than in each of them.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    RLSSessionDep,
    plugin_scope_by,
    get_current_active_user,
    GuildContextDep,
)
from app.core.plugin_scopes import PluginScopeAccess, scope_name, tool_resource
from app.core.messages import GuildMessages, InitiativeMessages
from app.core.tools import ARCHIVE_TARGETS, KINDS, Tool, plural_of
from app.models.platform.user import User
from app.models.tenant._mixins import archive_models
from app.schemas.tenant.archive import ArchivableType, ArchiveResponse
from app.services.permissions import Action
from app.services.tenant import archive as archive_service

router = APIRouter(route_class=ActorRoute)


def _governing(entity_type: str) -> Tool:
    """The tool whose sharing answers for this kind: its own, or the one it
    lives in."""
    return KINDS[entity_type].parent or Tool(entity_type)


#: What an installed plug-in needs to archive each kind: the write scope of the tool
#: whose sharing governs it. An initiative is the guild admins' to archive, so
#: no plug-in may ask for one.
_ARCHIVE_SCOPES: dict[str, str] = {
    target: scope_name(tool_resource(_governing(target)), PluginScopeAccess.write)
    for target in ARCHIVE_TARGETS
    if target != "initiative"
}
ArchiveWrite = Annotated[
    ActorContext, Depends(plugin_scope_by("entity_type", _ARCHIVE_SCOPES))
]

#: Wire name -> the model it addresses. Derived from the mixin: the archivable
#: models are the ones carrying ``ArchiveMixin``, and a target's table is its
#: own plural, so neither half is written down twice. A target with no
#: archivable model behind it fails at import rather than at request time.
_BY_TABLE = {model.__tablename__: model for model in archive_models()}
ARCHIVE_REGISTRY: dict[str, type] = {
    target.value: _BY_TABLE[plural_of(target.value)] for target in ArchivableType
}


async def _load(session: AsyncSession, entity_type: str, entity_id: int) -> Any:
    """The row, with what the access decision needs already on it.

    Every tool carries ``initiative`` and ``grants``, so one loader serves them
    all, and a row inside a tool is loaded with its tool's; an initiative is
    loaded for its own check below. RLS has already decided whether the row is
    visible at all, so a miss here is a 404 in the ordinary way.
    """
    model = ARCHIVE_REGISTRY[entity_type]
    stmt = select(model).where(model.id == entity_id)
    inside = KINDS[entity_type].parent if entity_type != "initiative" else None
    if inside is not None:
        tool = ARCHIVE_REGISTRY[inside.value]
        via = getattr(model, inside.value)
        stmt = stmt.options(
            selectinload(via).selectinload(tool.grants),
            selectinload(via).selectinload(tool.initiative),
            selectinload(via).undefer(tool.actions),
        )
    elif entity_type != "initiative":
        stmt = stmt.options(
            selectinload(model.initiative),
            selectinload(model.grants),
            undefer(model.actions),
        )
    row = (await session.exec(stmt)).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND[entity_type]
        )
    return row


#: The "no such thing" code per kind — a tool's own, the one a row inside a
#: tool is refused with, and the initiative's.
_NOT_FOUND: dict[str, str] = {
    **{t.value: resource_access.RESOURCE_ACCESS[t].not_found_msg for t in Tool},
    **{
        target: resource_access.SUB_TOOLS[ARCHIVE_REGISTRY[target]].not_found
        for target in ARCHIVE_TARGETS
        if target in KINDS and KINDS[target].parent
    },
    "initiative": InitiativeMessages.NOT_FOUND,
}


def _authorize(
    entity_type: str,
    row: Any,
    user: User | None,
    guild_context: ActorContext,
) -> None:
    """Who may put this away, and who may take it back out.

    A tool answers to its own sharing, like any other write to it. A row inside
    a tool, like a task, answers to the tool it is in. An initiative answers to the guild admins:
    archiving one hides it from every member's sidebar and freezes everything
    inside it, which is a guild-wide act rather than one initiative's.

    Either direction asks for the change the row's state allows: an edit
    while it is live, taking it back out once it is archived — so archiving
    one that is already archived answers with the stamp it has rather than
    refusing. The write itself is a lifecycle column, which is all the database
    will accept here either way.
    """
    if entity_type == "initiative":
        if not guild_context.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=GuildMessages.COMMUNITY_ADMIN_REQUIRED,
            )
        return
    governing = _governing(entity_type)
    subject = row if governing.value == entity_type else getattr(row, governing.value)
    resource_access.authorize(
        governing,
        subject,
        user,
        action=Action.unarchive if subject.archived_at is not None else Action.edit,
        context=guild_context,
    )


@router.post("/archive/{entity_type}/{entity_id}", response_model=ArchiveResponse)
async def archive_entity(
    entity_type: ArchivableType,
    entity_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ArchiveWrite,
) -> ArchiveResponse:
    """Mark a thing finished with, and everything inside it. Idempotent: an
    already-archived row keeps the stamp it has, so the date means when it was
    archived, not when it was last asked about."""
    row = await _load(session, entity_type.value, entity_id)
    _authorize(entity_type.value, row, current_user, guild_context)
    # Read the stamp back from the service, not off the row: committing expires
    # the instance, and reaching for the column afterwards would be a lazy load
    # with no async context to run in.
    stamp = await archive_service.archive_entity(session, row)
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
    """Take it back out, and with it everything that archiving took. Anything
    inside that was archived on its own occasion stays archived. Idempotent on a
    live row."""
    row = await _load(session, entity_type.value, entity_id)
    _authorize(entity_type.value, row, current_user, guild_context)
    await archive_service.unarchive_entity(session, row)
    await session.commit()
    return ArchiveResponse(
        entity_type=entity_type, entity_id=entity_id, archived_at=None
    )
