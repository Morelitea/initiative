"""Integration tests for guild context resolution.

Guild-scoped requests address their guild through the ``/g/{guild_id}`` path
segment. The guild is only a selector, never a trust boundary: membership (or a
live PAM grant) is validated fresh on every request, so a forged or stale path
can never read another guild's data.

``users.active_guild_id`` survives as the user's last-viewed-guild hint, set by
``PUT /users/me/guild-context`` and validated fail-closed there. It no longer
resolves guild-scoped HTTP requests (the path does), so these tests cover the
context endpoint's own validation and the per-request fail-closed check on the
path-addressed guild.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
    get_guild_headers,
)


@pytest.mark.integration
async def test_set_guild_context_for_member(client: AsyncClient, session: AsyncSession):
    """A member can enter their guild; the flag round-trips on UserRead."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)

    response = await client.put(
        "/api/v1/users/me/guild-context",
        headers=get_auth_headers(user),
        json={"guild_id": guild.id},
    )
    assert response.status_code == 200
    assert response.json()["active_guild_id"] == guild.id

    me = await client.get("/api/v1/users/me", headers=get_auth_headers(user))
    assert me.json()["active_guild_id"] == guild.id


@pytest.mark.integration
async def test_set_guild_context_null_enters_personal_mode(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    headers = await get_guild_headers(session, guild, user)

    response = await client.put(
        "/api/v1/users/me/guild-context",
        headers=headers,
        json={"guild_id": None},
    )
    assert response.status_code == 200
    assert response.json()["active_guild_id"] is None


@pytest.mark.integration
async def test_set_guild_context_rejects_non_member_without_confirming_existence(
    client: AsyncClient, session: AsyncSession
):
    """Fail closed: not a member, no live grant → 403, whether or not the
    guild exists."""
    user = await create_user(session)
    other = await create_user(session)
    foreign_guild = await create_guild(session, creator=other)
    await create_guild_membership(session, user=other, guild=foreign_guild)

    for guild_id in (foreign_guild.id, foreign_guild.id + 999):
        response = await client.put(
            "/api/v1/users/me/guild-context",
            headers=get_auth_headers(user),
            json={"guild_id": guild_id},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "GUILD_ACCESS_DENIED"


@pytest.mark.integration
async def test_non_member_gets_403_on_guild_path(
    client: AsyncClient, session: AsyncSession
):
    """Defense in depth: a non-member addressing a guild's path is rejected on
    every guild-scoped request — never another guild's data. The auth token
    carries no guild context; the path is the only selector and it is validated
    against real membership."""
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
    """Membership in guild A grants no access to guild B's path — the guild is
    resolved from the path and validated per request, so addressing a guild the
    caller can't access fails closed regardless of any held context."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    # The user is "in" their own guild (active_guild_id set), yet still cannot
    # reach a foreign guild's path.
    headers = await get_guild_headers(session, guild, user)

    other = await create_user(session)
    foreign = await create_guild(session, creator=other)
    await create_guild_membership(session, user=other, guild=foreign)

    response = await client.get(f"/api/v1/g/{foreign.id}/initiatives/", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_ACCESS_DENIED"
