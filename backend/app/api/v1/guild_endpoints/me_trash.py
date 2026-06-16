"""Cross-guild personal trash — the user's own deletions across every guild.

Deliberately a separate API from the guild-admin trash (``trash.py``): this is
user-scoped (``UserSessionDep``) and aggregates each guild the caller belongs
to, whereas the guild view is a single guild's everything and admin-only. The
two query genuinely different things, so they live in separate modules even
though both read the per-guild trash tables (the shared per-guild collection
logic is imported from ``trash``).
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import UserSessionDep, get_current_active_user
from app.api.v1.guild_endpoints.trash import _collect_trash_items
from app.models.user import User
from app.schemas.trash import TrashItem, TrashListResponse
from app.services.cross_guild import gather_across_guilds, member_guild_ids

# Mounted under /api/v1/me (no guild path segment) — see api.py.
me_router = APIRouter()


@me_router.get("/trash", response_model=TrashListResponse)
async def list_my_trash(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> TrashListResponse:
    """The current user's trashed entities across every guild they belong to.

    User-scoped: shows what *you* deleted, in any guild — this is the personal
    trash on the user settings page. The all-guild view (everything in one
    guild's trash) is the separate admin-only ``GET /g/{guild_id}/trash/``.
    Restore/purge stay guild-scoped; the client addresses them with each item's
    ``guild_id``. ``retention_days`` is per-guild, so it is omitted here.
    """
    target_guilds = await member_guild_ids(session, current_user.id)
    name_cache: dict[Optional[int], str] = {}

    async def _fetch(guild_session: AsyncSession, guild_id: int) -> list[TrashItem]:
        return await _collect_trash_items(
            guild_session,
            guild_id,
            only_deleted_by=current_user.id,
            name_cache=name_cache,
        )

    items = await gather_across_guilds(session, current_user.id, target_guilds, _fetch)
    items.sort(key=lambda i: i.deleted_at, reverse=True)
    return TrashListResponse(items=items, total=len(items), retention_days=None)
