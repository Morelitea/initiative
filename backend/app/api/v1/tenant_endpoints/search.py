"""`/api/v1/g/{guild_id}/search` — one query across everything in a guild.

Guild-scoped like any other content endpoint: the guild comes from the path and
``RLSSessionDep`` routes into its schema, so the index answers under the same
gates as the content it mirrors.
"""

from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import GuildContext, RLSSessionDep, get_guild_membership
from app.core.search import SearchEntityType
from app.db.search_index import entity_types
from app.models.platform.user import User
from app.schemas.tenant.search import SearchResults, SearchSuggestion
from app.services.tenant import search as search_service
from app.api.deps import get_current_active_user

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]

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
        types=types,
        initiative_id=initiative_id,
        limit=limit,
        offset=offset,
    )


@router.get("/suggest", response_model=List[SearchSuggestion])
async def suggest_guild(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    q: str = Query(description="What to jump to.", max_length=200),
    types: Optional[List[SearchEntityType]] = Query(
        default=None, description=_TYPE_DESCRIPTION
    ),
    limit: int = Query(default=search_service.SUGGEST_LIMIT, ge=1),
) -> List[SearchSuggestion]:
    """Titles for the command palette — a way to reach one thing quickly.

    Takes the same ``types`` as the search itself, so the palette and the
    results page can be narrowed to the same slice of the guild.
    """
    return await search_service.suggest(
        session,
        query=q,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
        types=types,
        limit=limit,
    )
