"""Guests: outside people in a community for a set time.

A guest's membership is a ``guild_memberships`` row with ``guest_until`` set.
The database stops admitting it at that moment
(``authorization.live_membership``); the sweep here then removes it through
the one removal path, so everything a membership carries goes with it.
"""

from __future__ import annotations

import logging
from functools import partial

from sqlalchemy import func
from sqlmodel import col, select

from app.db import post_commit
from app.db.request_context import Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import GuildMembership
from app.services.content_sockets import sockets as content_sockets
from app.services.guild_sweeps import Scope, each_guild
from app.services.platform import guilds as guilds_service

logger = logging.getLogger(__name__)

#: How often the sweep looks for guests whose time has run out.
GUEST_EXPIRY_POLL_SECONDS = 300


async def end_expired_guests() -> None:
    """Remove each guest membership whose ``guest_until`` has passed."""
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as session:
        await set_rls_context(session, Unattributed())
        expired = (
            await session.exec(
                select(GuildMembership.guild_id, GuildMembership.user_id).where(
                    col(GuildMembership.guest_until) <= func.now()
                )
            )
        ).all()
    by_guild: dict[int, list[int]] = {}
    for guild_id, user_id in expired:
        by_guild.setdefault(guild_id, []).append(user_id)
    if not by_guild:
        return

    async def end(session, guild_id: int) -> None:
        for user_id in by_guild[guild_id]:
            # Removed only while the row is still an ended guest's: the person
            # may have been removed and come back since the list was read.
            if await guilds_service.remove_user_from_guild(
                session,
                guild_id=guild_id,
                user_id=user_id,
                actor_user_id=None,
                via="expired",
                only_if=col(GuildMembership.guest_until) <= func.now(),
            ):
                post_commit.after_commit(
                    session, partial(content_sockets.revoke_user, guild_id, user_id)
                )
        await session.commit()

    await each_guild(
        [(Scope.PROVISIONED, end)], name="guest-expiry", only=set(by_guild)
    )
    logger.info("guests: ended %s expired", len(expired))
