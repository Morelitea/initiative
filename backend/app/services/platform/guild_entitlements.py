"""What an operator has granted one guild.

The single read of ``guild_administration.auth_options``. Both the management
gates and the just-in-time provisioning check come through here, so "has this
guild been granted X" is one query with one answer.
"""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.guild_auth_options import GuildAuthOption
from app.models.platform.guild_administration import GuildAdministration


async def auth_options_for(
    session: AsyncSession, guild_id: int
) -> frozenset[GuildAuthOption]:
    """The sign-in options this guild holds. Empty when it holds none, and
    empty when it has no administration row at all — a guild nobody has granted
    anything is the same as a guild with nothing granted."""
    administration = (
        await session.exec(
            select(GuildAdministration).where(GuildAdministration.guild_id == guild_id)
        )
    ).one_or_none()
    if administration is None:
        return frozenset()
    resolved = set()
    for value in administration.auth_options or ():
        try:
            resolved.add(GuildAuthOption(value))
        except ValueError:
            continue
    return frozenset(resolved)


async def has_auth_option(
    session: AsyncSession, guild_id: int, option: GuildAuthOption
) -> bool:
    return option in await auth_options_for(session, guild_id)
