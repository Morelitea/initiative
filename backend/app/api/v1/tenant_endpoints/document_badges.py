"""`/api/v1/g/{guild_id}/document-badges` — what a document's chips say now.

Guild-scoped like any other content read: the guild comes from the path and
``RLSSessionDep`` routes into its schema, so a badge answers under the same
gates as the thing it is about.
"""

from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, Query

from app.api.deps import GuildContext, RLSSessionDep, get_current_active_user
from app.api.deps import get_guild_membership
from app.core.document_badges import BadgeKind
from app.models.platform.user import User
from app.schemas.tenant.document_badge import BadgeStateList
from app.services.tenant import document_badges as badges_service

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]

_REF_DESCRIPTION = (
    "A chip to read, as `kind:id:aspect` — `task:12:status`. Repeat it for "
    "every chip on the page; they are read together. Pairs that name no badge "
    "are ignored. Available: " + ", ".join(kind.value for kind in BadgeKind)
)


@router.get("/", response_model=BadgeStateList)
async def read_badges(
    session: RLSSessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    _guild_context: GuildContextDep,
    ref: List[str] = Query(
        default=[], max_length=badges_service.MAX_REFS, description=_REF_DESCRIPTION
    ),
) -> BadgeStateList:
    """Read every chip on one page in one request.

    A reference that names something gone, or something this caller may not
    see, is absent from the answer — the two are the same reply, and the chip
    falls back to the words the document stored beside it.
    """
    return BadgeStateList(items=await badges_service.read_badges(session, refs=ref))
