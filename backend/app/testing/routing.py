"""Routing a test session the way a request is routed.

A test that wants a session inside a community's schema used to write the
routing by hand, naming the role it wanted to be. There is no such parameter
any more: who somebody is in a community is a row, and what that gives them is
computed by the establishment seam. So a test asks the seam, exactly as a
request does — which is also what makes the test's own setup honest, because a
routing now needs a membership or a grant to exist first.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Sequence

from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User

__all__ = ["as_role", "route_as", "route_as_install", "route_system"]


async def route_as(
    session: AsyncSession,
    *,
    user_id: int,
    guild_id: int,
    satisfied_providers: Optional[Sequence[int] | str] = None,
    settings: bool = False,
    seat: bool = False,
):
    """Route ``session`` into ``guild_id`` as ``user_id``, through the seam.

    Returns the ``GuildContext`` the seam built, so a test can assert on the
    standing it computed. Raises ``GuildAccessError`` when the account reaches
    the community by neither membership nor a live grant — the same refusal the
    request path gives.

    ``settings`` is what the community's configuration and roster routes ask
    for — the surface a settings grant may serve. ``seat`` is what its four
    seat routes ask for, and it is honoured only where the seat is reached —
    the same two conditions the request path applies.
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
        for_settings=settings or seat,
        for_seat=seat,
    )


async def route_as_install(
    session: AsyncSession,
    *,
    guild_id: int,
    install_id: int,
    client_id: str,
    scopes: Sequence[str],
    initiative_id: Optional[int] = None,
    user_id: Optional[int] = None,
    purpose: Optional[str] = None,
):
    """Route ``session`` as an installed app, through the install seam.

    What the token path will hand the seam once it verifies a token, built
    here from the values a test chose; ``user_id`` makes it a member token.
    Returns the ``InstallContext`` the seam built, and raises
    ``InstallAccessError`` when the install may not act.
    """
    from app.api.deps import VerifiedInstall, establish_install_access

    return await establish_install_access(
        session,
        VerifiedInstall(
            guild_id=guild_id,
            install_id=install_id,
            client_id=client_id,
            scopes=frozenset(scopes),
            initiative_id=initiative_id,
            user_id=user_id,
            purpose=purpose,
        ),
    )


async def route_system(session: AsyncSession, *, guild_id: int, **kwargs) -> None:
    """Route ``session`` into one community's schema with nobody behind it —
    what a sweep, a poller or a lifecycle job does."""
    from app.db.session import set_rls_context

    await set_rls_context(session, guild_id=guild_id, **kwargs)


@asynccontextmanager
async def as_role(
    session: AsyncSession, role: str, user_id: int
) -> AsyncIterator[None]:
    """Run the block as the Postgres ``role`` with ``user_id`` as the current
    user, on the session's connection, then return to the login role.

    For a table's grants and policies read as a request role reads them, with
    none of the routing a request does first.
    """
    await session.exec(
        text(
            "SELECT set_config('app.current_user_id', :uid, false), "
            "set_config('role', :role, false)"
        ),
        params={"uid": str(user_id), "role": role},
    )
    try:
        yield
    finally:
        await session.exec(
            text(
                "SELECT set_config('role', 'none', false), "
                "set_config('app.current_user_id', '', false)"
            )
        )
