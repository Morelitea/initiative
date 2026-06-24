"""Integration tests for path-based guild access control.

Guild-scoped requests address their guild through the ``/g/{guild_id}`` path
segment. The guild is only a selector, never a trust boundary: membership (or a
live PAM grant) is validated fresh on every request, so a forged path can never
read another guild's data. There is no server-held guild context anymore — the
URL is the single source of truth, per request and per tab.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)


@pytest.mark.integration
async def test_non_member_gets_403_on_guild_path(
    client: AsyncClient, session: AsyncSession
):
    """A non-member addressing a guild's path is rejected — never another
    guild's data. The auth token carries no guild context; the path is the only
    selector and it is validated against real membership."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)

    outsider = await create_user(session)

    response = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/", headers=get_auth_headers(outsider)
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_ACCESS_DENIED"


@pytest.mark.integration
async def test_member_of_one_guild_cannot_address_another(
    client: AsyncClient, session: AsyncSession
):
    """Membership in guild A grants no access to guild B's path — each request's
    guild is resolved from its path and validated independently, so two tabs in
    two guilds never bleed into each other."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)

    other = await create_user(session)
    foreign = await create_guild(session, creator=other)
    await create_guild_membership(session, user=other, guild=foreign)

    # Authenticated as a member of `guild`, but addressing `foreign`'s path.
    response = await client.get(
        f"/api/v1/g/{foreign.id}/initiatives/", headers=get_auth_headers(user)
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_ACCESS_DENIED"
