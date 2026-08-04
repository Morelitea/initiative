"""Cross-guild personal AI — the member's own key + connection preference across
every guild they belong to.

Follows the My Tasks / My Trash pattern: a user-scoped aggregate READ
(``UserSessionDep`` + ``gather_across_guilds``) that visits each guild's schema
and merges. Writes (attach key, set preference) stay guild-scoped — the client
addresses them with each section's ``guild_id`` via
``/g/{guild_id}/settings/ai/me/*``. There is no cross-guild write here, exactly
like task edits stay under ``/g/{guild_id}``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import UserSessionDep, get_current_active_user
from app.db.session import set_rls_context
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.schemas.ai_settings import MyAIConnectionRow
from app.services.ai_settings import get_member_ai_view
from app.services.cross_guild import gather_across_guilds, member_guild_ids

# Mounted under /api/v1/me (no guild path segment) — see api.py.
me_router = APIRouter()


@me_router.get("/ai", response_model=list[MyAIConnectionRow])
async def list_my_ai(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[MyAIConnectionRow]:
    """Every AI connection available to the member, flattened across the guilds
    they belong to — a visibility list of what they can use plus their own-key
    state. Connections come from the active mode (the operator's in platform
    mode, or a guild's own in guild mode); the key/preference are the member's,
    per guild. Shared-key connections they can't attach to are still listed.
    """
    target_guilds = await member_guild_ids(session, current_user.id)

    # Guild names up-front under the user-only context (the user is a member, so
    # RLS admits these rows), so each row carries its guild's name without a
    # per-guild shared-table read inside the routed loop.
    await set_rls_context(session, user_id=current_user.id)
    name_rows = await session.exec(
        select(Guild.id, Guild.name).where(Guild.id.in_(tuple(target_guilds)))
    )
    names = {gid: name for gid, name in name_rows}

    async def _fetch(
        guild_session: AsyncSession, guild_id: int
    ) -> list[MyAIConnectionRow]:
        view = await get_member_ai_view(guild_session, current_user, guild_id)
        return [
            MyAIConnectionRow(
                guild_id=guild_id,
                guild_name=names.get(guild_id, ""),
                scope=c.scope,
                connection_id=c.id,
                label=c.label,
                provider=c.provider,
                model=c.model,
                allow_member_keys=c.allow_member_keys,
                has_member_key=c.has_member_key,
                requires_member_key=c.requires_member_key,
                is_selected=c.is_selected,
            )
            for c in view.connections
        ]

    return await gather_across_guilds(session, current_user.id, target_guilds, _fetch)
