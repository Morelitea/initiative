"""`/api/v1/recents` — mixed-type recent items for the header tabs bar.

The tabs bar is special-cased by design (guild-context design doc §3.5a): it
renders entities from ANY of the user's guilds regardless of the current
context, but only their render metadata (name/icon/type) — never their
content. So the list runs under USER context and gathers each member guild's
``recent_views`` from its own schema, enriches + permission-filters inside
that guild's routed context, and merges by ``last_viewed_at``. Opening a tab
navigates into the entity's guild (which sets the server-held context) before
any content is fetched.

Closing a tab is the one cross-guild write: a guild-ADDRESSED delete
(``?guild_id=``, validated like any context) of the caller's own row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Callable, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    UserSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.tools import RECENTABLE_TOOLS, Tool
from app.services.tenant.tags import TOOL_TAG_LINKS
from app.models.tenant.document import Document
from app.models.platform.guild import GuildMembership
from app.models.tenant.initiative import Initiative
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.recent_view import RecentView
from app.models.platform.user import User
from app.schemas.tenant.recent_view import RecentItemRead
from app.services import permissions as permissions_service
from app.services.tenant import recent_views as recent_views_service
from app.services.cross_guild import gather_across_guilds
from app.services.tenant.recent_views import RecentEntityType


router = APIRouter()
# Guild-scoped sub-router: closing a tab (the delete) is the one guild-scoped
# recents operation and mounts under /g/{guild_id}/recents. The cross-guild
# tabs-bar list stays on the top-level router above — fully separate endpoints.
guild_router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


@dataclass(frozen=True)
class RecentToolSpec:
    """How one tool's recent-view rows become tab items.

    Derived per tool, not hand-listed: the model comes from the tag registry
    (every tool is taggable) and the label column from the model's own
    ``_display_field``. Resolution is otherwise uniform — every recentable tool
    is a DAC resource with ``grants`` + ``initiative``, so it eager-loads the
    same way and authorizes through ``DAC_RESOURCES[tool]``.
    """

    model: type
    name_attr: str
    extra: Callable[[Any], Dict[str, Any]] | None = None


def _document_extra(document: Document) -> Dict[str, Any]:
    return {
        "document_type": (
            document.document_type.value if document.document_type is not None else None
        ),
        "mime_type": document.file_content_type,
        "original_filename": document.original_filename,
    }


# The only per-tool code here: render-only fields a tool's tab carries beyond
# the common id/name. Everything else about a tool — its model, its display
# column — is derived below, so adding a tool needs no edit in this module.
_RECENT_EXTRAS: dict[Tool, Callable[[Any], Dict[str, Any]]] = {
    Tool.project: lambda project: {"icon": project.icon},
    Tool.document: _document_extra,
}

RECENT_TOOL_SPECS: dict[Tool, RecentToolSpec] = {
    tool: RecentToolSpec(
        model=TOOL_TAG_LINKS[tool].entity,
        name_attr=TOOL_TAG_LINKS[tool].entity.display_field(),
        extra=_RECENT_EXTRAS.get(tool),
    )
    for tool in RECENTABLE_TOOLS
}

RECENT_SPECS_BY_ENTITY_TYPE: dict[str, tuple[Tool, RecentToolSpec]] = {
    tool.value: (tool, spec) for tool, spec in RECENT_TOOL_SPECS.items()
}


async def _enrich_recent_rows(
    session,
    current_user: User,
    rows: List[RecentView],
) -> List[RecentItemRead]:
    """Resolve one guild's recent_views rows into render-only tab items.

    Must run inside that guild's routed context — relationships and ids are
    per-schema, and ``require_access`` reads the role established for that
    guild, so a row reaches the same verdict here as on its detail page.
    """
    ids_by_type = recent_views_service.group_ids_by_type(rows)

    # One eager-load per tool that actually appears in this batch. Every
    # recentable tool is a DAC resource with the same ``grants`` + ``initiative``
    # shape, so the query is identical apart from the model.
    loaded: Dict[str, Dict[int, Any]] = {}
    for tool, spec in RECENT_TOOL_SPECS.items():
        ids = ids_by_type.get(tool.value)
        if not ids:
            continue
        model = spec.model
        stmt = (
            select(model)
            .where(model.id.in_(ids))
            .options(
                selectinload(model.grants).selectinload(ResourceGrant.role),
                selectinload(model.initiative).selectinload(Initiative.memberships),
            )
        )
        result = await session.exec(stmt)
        loaded[tool.value] = {row.id: row for row in result.all()}

    items: List[RecentItemRead] = []
    for row in rows:
        entry = RECENT_SPECS_BY_ENTITY_TYPE.get(row.entity_type)
        if entry is None:
            continue
        tool, spec = entry
        entity = loaded.get(row.entity_type, {}).get(row.entity_id)
        if entity is None or entity.guild_id is None:
            continue
        try:
            permissions_service.require_access(
                permissions_service.DAC_RESOURCES[tool],
                entity,
                current_user,
                access="read",
            )
        except HTTPException:
            # Permission denied / not found — drop the row from the bar but let
            # any other error bubble up so latent bugs stay visible.
            continue
        items.append(
            # ``model_construct`` skips the SanitizedBaseModel validator so
            # trusted DB columns (already sanitized on input) aren't
            # double-escaped on the way out — e.g. ``Foo & Bar`` would
            # otherwise round-trip as ``Foo &amp; Bar``.
            RecentItemRead.model_construct(
                # The member, not its value: ``model_construct`` skips
                # validation, so whatever is passed is what the field holds and
                # what the serializer is later handed.
                entity_type=RecentEntityType(tool.value),
                entity_id=entity.id,
                guild_id=entity.guild_id,
                initiative_id=getattr(entity, "initiative_id", None),
                name=getattr(entity, spec.name_attr),
                last_viewed_at=row.last_viewed_at,
                **(spec.extra(entity) if spec.extra else {}),
            )
        )

    return items


@router.get("/", response_model=List[RecentItemRead])
async def list_recents(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[RecentItemRead]:
    """Recent tabs across every guild the user belongs to (names only).

    Works identically with a guild context or in personal mode: the result
    depends only on who is asking, never on what they're currently viewing.
    """
    # The guilds to visit, from the shared memberships table (the user context
    # shows the caller's own rows).
    member_guilds = [
        gid
        for gid in (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == current_user.id
                )
            )
        ).all()
    ]

    limit = recent_views_service.clamp_recent_limit(current_user.recent_tabs_limit)

    async def _fetch(guild_session, guild_id: int) -> List[RecentItemRead]:  # type: ignore[no-untyped-def]
        rows = await recent_views_service.list_recent_views(
            guild_session, user_id=current_user.id, limit=limit
        )
        if not rows:
            return []
        return await _enrich_recent_rows(guild_session, current_user, list(rows))

    items = await gather_across_guilds(session, current_user.id, member_guilds, _fetch)
    items.sort(key=lambda item: item.last_viewed_at, reverse=True)
    return items[:limit]


@guild_router.delete(
    "/{entity_type}/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_recent(
    entity_type: RecentEntityType,
    entity_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Close a tab: delete the caller's own recent-view row.

    Guild-scoped — mounted under /g/{guild_id}/recents because a tab can belong
    to any of the user's guilds and per-schema ids are only unique within a
    guild. Idempotent.
    """
    del guild_context  # validation + routing happen in the dependency
    await recent_views_service.clear_view(
        session,
        user_id=current_user.id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
