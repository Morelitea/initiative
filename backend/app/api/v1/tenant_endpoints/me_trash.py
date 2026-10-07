"""Cross-guild personal trash — the user's own deletions across every guild.

Deliberately a separate API from the guild-admin trash (``trash.py``): this is
user-scoped (``UserSessionDep``) and aggregates each guild the caller belongs
to, whereas the guild view is a single guild's everything and admin-only. The
two query genuinely different things, so they live in separate modules even
though both read the per-guild trash tables (one guild's window,
``trash.trash_page``, is shared).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import UserSessionDep, get_current_active_user
from app.api.v1.tenant_endpoints.trash import TrashPage, TrashPageSize, trash_page
from app.db.query import build_paginated_response
from app.models.platform.user import User
from app.schemas.tenant.trash import TrashItem, TrashListResponse
from app.services.cross_guild import member_guild_ids, page_across_guilds

# Mounted under /api/v1/me (no guild path segment) — see api.py.
me_router = APIRouter()


@me_router.get("/trash", response_model=TrashListResponse)
async def list_my_trash(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    page: TrashPage = 1,
    page_size: TrashPageSize = 50,
) -> TrashListResponse:
    """The current user's trashed entities across every guild they belong to,
    newest first.

    User-scoped: shows what *you* deleted, in any guild — this is the personal
    trash on the user settings page. The all-guild view (everything in one
    guild's trash) is the separate admin-only ``GET /c/{community_id}/trash/``.
    Restore/purge stay guild-scoped; the client addresses them with each item's
    ``guild_id``. ``retention_days`` is per-guild, so it is omitted here.
    """
    target_guilds = await member_guild_ids(session, current_user.id)

    async def _newest(
        guild_session: AsyncSession, guild_id: int, limit: int
    ) -> tuple[list[TrashItem], int]:
        return await trash_page(
            guild_session, guild_id, only_deleted_by=current_user.id, limit=limit
        )

    window, total_count = await page_across_guilds(
        session,
        current_user.id,
        target_guilds,
        _newest,
        order=lambda item: (item.deleted_at, (item.entity_type, item.entity_id)),
        descending=True,
        page=page,
        page_size=page_size,
    )
    return TrashListResponse(
        **build_paginated_response(
            [item for _, item in window], total_count, page, page_size
        )
    )
