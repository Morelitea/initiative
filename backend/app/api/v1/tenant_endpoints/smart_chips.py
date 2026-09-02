"""`/api/v1/g/{guild_id}/smart-chips` — what a document's chips say now.

Guild-scoped like any other content read: the guild comes from the path and
``RLSSessionDep`` routes into its schema, so a chip answers under the same
gates as the thing it is about.
"""

from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, Query

from app.api.deps import GuildContext, RLSSessionDep, get_current_active_user
from app.api.deps import get_guild_membership
from app.core.smart_chips import SmartChipKind
from app.models.platform.user import User
from app.schemas.tenant.smart_chip import SmartChipStateList
from app.services.tenant import smart_chips as smart_chips_service

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]

_REF_DESCRIPTION = (
    "A chip to read, as `kind:id:aspect` — `task:12:status`. Repeat it for "
    "every chip on the page; they are read together. Pairs that name no chip "
    "are ignored. Available: " + ", ".join(kind.value for kind in SmartChipKind)
)


@router.get("/kinds", response_model=List[SmartChipKind])
async def list_smart_chip_kinds(
    _current_user: Annotated[User, Depends(get_current_active_user)],
    _guild_context: GuildContextDep,
) -> List[SmartChipKind]:
    """The chips an editor may offer to insert.

    Asked for rather than assumed, so an editor cannot put a chip in a
    document that this server has no reader for — and gains one the day a
    reader is added, without being told.

    Titles are not here: every referenceable thing has one, and it is how a
    reference renders rather than something chosen from a menu.
    """
    return list(SmartChipKind)


@router.get("/", response_model=SmartChipStateList)
async def read_smart_chips(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    _guild_context: GuildContextDep,
    ref: List[str] = Query(
        default=[],
        max_length=smart_chips_service.MAX_REFS,
        description=_REF_DESCRIPTION,
    ),
) -> SmartChipStateList:
    """Read every chip on one page in one request.

    A reference that names something gone, or something this caller may not
    see, is absent from the answer — the two are the same reply, and the chip
    falls back to the words the document stored beside it.
    """
    return SmartChipStateList(
        items=await smart_chips_service.read_smart_chips(
            session,
            user_id=current_user.id,
            refs=ref,
        )
    )
