"""Routing a test session the way a request is routed.

A test that wants a session inside a community's schema used to write the
routing by hand, naming the role it wanted to be. There is no such parameter
any more: who somebody is in a community is a row, and what that gives them is
computed by the establishment seam. So a test asks the seam, exactly as a
request does — which is also what makes the test's own setup honest, because a
routing now needs a membership or a grant to exist first.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User

__all__ = ["route_as", "route_system"]


async def route_as(
    session: AsyncSession,
    *,
    user_id: int,
    guild_id: int,
    satisfied_providers: Optional[Sequence[int] | str] = None,
    seat: bool = False,
):
    """Route ``session`` into ``guild_id`` as ``user_id``, through the seam.

    Returns the ``GuildContext`` the seam built, so a test can assert on the
    standing it computed. Raises ``GuildAccessError`` when the account reaches
    the community by neither membership nor a live grant — the same refusal the
    request path gives.

    ``seat`` is what the community's four configuration routes ask for, and it
    is honoured only where the seat is reached — the same two conditions the
    request path applies.
    """
    from app.api.deps import establish_guild_access
    from app.core import auth_context
    from app.db.session import set_rls_context

    # What this session's credential proved, the way the validator records it
    # on a request: the seam reads it for the community's sign-in rule, and
    # passes it on to the GUC the policies read.
    if satisfied_providers is not None:
        auth_context.set_satisfied_providers(
            satisfied_providers
            if isinstance(satisfied_providers, str)
            else frozenset(satisfied_providers)
        )
    await set_rls_context(session, user_id=user_id)
    user = (await session.exec(select(User).where(User.id == user_id))).one()
    return await establish_guild_access(
        session,
        user,
        guild_id,
        satisfied_providers=satisfied_providers,
        for_settings=seat,
        for_seat=seat,
    )


async def route_system(session: AsyncSession, *, guild_id: int, **kwargs) -> None:
    """Route ``session`` into one community's schema with nobody behind it —
    what a sweep, a poller or a lifecycle job does."""
    from app.db.session import set_rls_context

    await set_rls_context(session, guild_id=guild_id, **kwargs)
