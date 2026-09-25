"""`/api/v1/c/{guild_id}/search` — one query across everything in a guild.

Guild-scoped like any other content endpoint: the guild comes from the path and
``RLSSessionDep`` routes into its schema, so the index answers under the same
gates as the content it mirrors.

An installed app may call ``/suggest`` (``history/app-principal-design.md``).
The scope it needs depends on the ``types`` it asks for, so the route takes
:func:`app.api.deps.app_scope_checked` and the service narrows ``types`` to the
kinds the install may read.
"""

from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    GuildContext,
    RLSSessionDep,
    app_scope_checked,
    get_current_active_user,
    get_guild_membership,
)
from app.core.references import parse_ref
from app.core.search import SearchEntityType
from app.db.app_rls import SEARCH_ENTRY_READ_SCOPE
from app.db.guild_standing import InstallContext
from app.db.search_index import entity_types
from app.models.platform.user import User
from app.schemas.tenant.search import SearchResults, SearchSuggestion
from app.services.tenant import search as search_service

router = APIRouter(route_class=ActorRoute)

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
#: ``/suggest`` for a person or an installed app. An app needs the read scope
#: of each kind it asks for, which the service checks once it has ``types``.
SuggestByEntityType = Annotated[
    ActorContext,
    Depends(
        app_scope_checked(
            {f"{resource.value}:read" for resource in SEARCH_ENTRY_READ_SCOPE.values()},
            per="entity type",
        )
    ),
]

_ARCHIVED_DESCRIPTION = (
    "Include archived work. Left out by default, so a search answers with what "
    "is in play."
)
_TEMPLATE_DESCRIPTION = (
    "Omit for both. ``true`` returns only templates (a template picker), "
    "``false`` only real content (a picker choosing where content goes)."
)
_SUBJECT_DESCRIPTION = (
    "The thing being written in, as a reference (``document:12``). It is left "
    "out of the answer: a thing does not point at itself. A reference that "
    "names nothing narrows nothing."
)
_TYPE_DESCRIPTION = (
    "Restrict to these entity types. Omit for the default scope "
    f"({', '.join(t.value for t in entity_types(default_scope_only=True))}); "
    "naming a type "
    "reaches it explicitly."
)


@router.get("/", response_model=SearchResults)
async def search_guild(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    q: str = Query(description="What to search for.", max_length=1000),
    types: Optional[List[SearchEntityType]] = Query(
        default=None, description=_TYPE_DESCRIPTION
    ),
    initiative_id: Optional[int] = Query(
        default=None, description="Restrict to one initiative."
    ),
    include_archived: bool = Query(default=False, description=_ARCHIVED_DESCRIPTION),
    template: Optional[bool] = Query(default=None, description=_TEMPLATE_DESCRIPTION),
    limit: int = Query(default=20, ge=1, le=search_service.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> SearchResults:
    """Ranked matches across the guild's tools, comments and tags.

    ``total`` counts entities the caller may see, so it is what a pager should
    show rather than an estimate to correct later.
    """
    return await search_service.search(
        session,
        query=q,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
        filters=search_service.Filters(
            types=types,
            initiative_id=initiative_id,
            include_archived=include_archived,
            template=template,
        ),
        limit=limit,
        offset=offset,
    )


@router.get("/recent", response_model=List[SearchSuggestion])
async def recent_guild(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    types: Optional[List[SearchEntityType]] = Query(
        default=None, description=_TYPE_DESCRIPTION
    ),
    initiative_id: Optional[int] = Query(
        default=None, description="Restrict to one initiative."
    ),
    template: Optional[bool] = Query(default=None, description=_TEMPLATE_DESCRIPTION),
    subject: Optional[str] = Query(default=None, description=_SUBJECT_DESCRIPTION),
    limit: int = Query(default=search_service.SUGGEST_LIMIT, ge=1),
) -> List[SearchSuggestion]:
    """What a picker offers before anything has been typed.

    The most recently changed things the caller could name, taking the same
    ``types``, ``initiative_id`` and ``template`` narrowing as the search — so
    what a picker suggests and what it finds are the same set of things.
    """
    return await search_service.recent(
        session,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
        filters=search_service.Filters(
            types=types,
            initiative_id=initiative_id,
            template=template,
            subject=parse_ref(subject) if subject else None,
        ),
        limit=limit,
    )


@router.get("/suggest", response_model=List[SearchSuggestion])
async def suggest_guild(
    session: ActorSessionDep,
    guild_context: SuggestByEntityType,
    q: str = Query(description="What to jump to.", max_length=200),
    types: Optional[List[SearchEntityType]] = Query(
        default=None, description=_TYPE_DESCRIPTION
    ),
    initiative_id: Optional[int] = Query(
        default=None, description="Restrict to one initiative."
    ),
    template: Optional[bool] = Query(default=None, description=_TEMPLATE_DESCRIPTION),
    subject: Optional[str] = Query(default=None, description=_SUBJECT_DESCRIPTION),
    limit: int = Query(default=search_service.SUGGEST_LIMIT, ge=1),
) -> List[SearchSuggestion]:
    """Titles for the command palette — a way to reach one thing quickly.

    Takes the same ``types`` as the search itself, so the palette and the
    results page can be narrowed to the same slice of the guild.

    An installed app is answered the kinds among ``types`` (the default scope
    when omitted) whose read scope it holds, in the initiatives it is placed
    in, and only what it could read through the tools themselves. Asking only
    for kinds it holds no read scope for is 403 (``APP_SCOPE_REQUIRED``).
    """
    install = guild_context if isinstance(guild_context, InstallContext) else None
    try:
        return await search_service.suggest(
            session,
            query=q,
            user_id=guild_context.user_id,
            guild_id=guild_context.guild_id,
            filters=search_service.Filters(
                types=types,
                initiative_id=initiative_id,
                template=template,
                subject=parse_ref(subject) if subject else None,
            ),
            limit=limit,
            install=install,
        )
    except search_service.SearchScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=exc.code
        ) from exc
