"""Helpers for endpoints that aggregate guild-scoped data across guilds.

Under schema-per-guild a routed session only sees one guild's schema, so a
"global" list (the user's items across every guild they belong to) has to visit
each guild's schema in turn and merge the results. Per-schema ids collide across
guilds, so callers must keep each item's ``guild_id`` and the identity map is
cleared between guilds.
"""

from typing import Awaitable, Callable, Optional, Sequence, TypeVar

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.models.guild import GuildMembership

T = TypeVar("T")


async def member_guild_ids(
    session: AsyncSession,
    user_id: int,
    *,
    restrict_to: Optional[Sequence[int]] = None,
) -> list[int]:
    """Guild ids the user belongs to, sorted (optionally intersected with
    ``restrict_to``). Routes to the user-only context so the user's own rows in
    the shared ``guild_memberships`` table are visible."""
    await set_rls_context(session, user_id=user_id)
    rows = await session.exec(
        select(GuildMembership.guild_id).where(GuildMembership.user_id == user_id)
    )
    ids = sorted(rows)
    if restrict_to is not None:
        allowed = set(restrict_to)
        ids = [gid for gid in ids if gid in allowed]
    return ids


async def gather_across_guilds(
    session: AsyncSession,
    user_id: int,
    guild_ids: Sequence[int],
    fetch: Callable[[AsyncSession, int], Awaitable[list[T]]],
) -> list[T]:
    """Route into each guild's schema, call ``fetch(session, guild_id)``, and
    concatenate the results. The identity map is expunged between guilds because
    ids are unique only within a schema, not across them."""
    results: list[T] = []
    for guild_id in guild_ids:
        # Expunge BEFORE each guild: a cached object with this schema's id (from a
        # prior guild, or anything already on the session) would otherwise be
        # returned by the identity map instead of this guild's row.
        session.expunge_all()
        await set_rls_context(session, user_id=user_id, guild_id=guild_id)
        results.extend(await fetch(session, guild_id))
    return results
