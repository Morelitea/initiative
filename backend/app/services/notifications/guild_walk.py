"""Visiting every live community once, for the notification sweeps."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.models.platform.guild import LIVE_STATUS_VALUES, Guild


async def live_guild_ids(session: AsyncSession) -> list[int]:
    """The communities a sweep visits: every one whose content is still live."""
    await set_rls_context(session)
    return list(
        (
            await session.exec(
                select(Guild.id)
                .where(Guild.status.in_(LIVE_STATUS_VALUES))
                .order_by(Guild.id.asc())
            )
        )
        .scalars()
        .all()
    )


async def per_guild(
    session: AsyncSession,
    visit: Callable[[AsyncSession, int], Awaitable[None]],
) -> None:
    """Run ``visit`` once in each live community, routed as the sweep.

    One statement per community rather than one per member of it: a sweep asks
    each community what is waiting, and only then goes near the people it is
    waiting for.
    """
    for guild_id in await live_guild_ids(session):
        session.expunge_all()
        await set_rls_context(session, guild_id=guild_id)
        await visit(session, guild_id)
        await session.commit()
    session.expunge_all()
    await set_rls_context(session)
