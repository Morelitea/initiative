"""A community that declines personal API keys: the switch, and what it means.

The rule is answered in three places and they have to agree — the switch on the
guild's own security surface, the mint, and every path that reaches the guild's
content with a key in hand.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_auth_headers,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]


async def _key_headers(client: AsyncClient, headers: dict, **body) -> dict[str, str]:
    """Mint a key for the caller and return the headers that present it."""
    created = await client.post(
        "/api/v1/users/me/api-keys", headers=headers, json={"name": "k", **body}
    )
    assert created.status_code == 201, created.text
    return {"Authorization": f"Bearer {created.json()['secret']}"}


# --- The switch -------------------------------------------------------------


async def test_the_seat_switches_api_access_and_the_guild_list_reads_it(
    client: AsyncClient, session: AsyncSession
):
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.security_admin
    )
    headers = get_auth_headers(admin)

    listed = await client.get("/api/v1/guilds/", headers=headers)
    assert [g["allow_api_keys"] for g in listed.json() if g["id"] == guild.id] == [True]

    off = await client.put(
        f"/api/v1/guilds/{guild.id}/api-access",
        headers=headers,
        json={"allow_api_keys": False},
    )
    assert off.status_code == 200, off.text
    assert off.json() == {"allow_api_keys": False}

    listed = await client.get("/api/v1/guilds/", headers=headers)
    assert [g["allow_api_keys"] for g in listed.json() if g["id"] == guild.id] == [
        False
    ]

    on = await client.put(
        f"/api/v1/guilds/{guild.id}/api-access",
        headers=headers,
        json={"allow_api_keys": True},
    )
    assert on.json() == {"allow_api_keys": True}


@pytest.mark.parametrize("role", [GuildRole.admin, GuildRole.member])
async def test_only_the_seat_switches_api_access(
    client: AsyncClient, session: AsyncSession, role: GuildRole
):
    """Running a community is not deciding what may be used to reach it."""
    user = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=role)

    response = await client.put(
        f"/api/v1/guilds/{guild.id}/api-access",
        headers=get_auth_headers(user),
        json={"allow_api_keys": False},
    )
    assert response.status_code == 403


async def test_api_access_needs_no_operator_entitlement(
    client: AsyncClient, session: AsyncSession
):
    """It only ever narrows what reaches the guild, so there is nothing for an
    operator to grant — unlike the sign-in requirement beside it."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin, auth_options=[])
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.security_admin
    )

    response = await client.put(
        f"/api/v1/guilds/{guild.id}/api-access",
        headers=get_auth_headers(admin),
        json={"allow_api_keys": False},
    )
    assert response.status_code == 200, response.text


# --- The mint ---------------------------------------------------------------


async def test_no_key_is_minted_into_a_guild_that_declines_them(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user, allow_api_keys=False)
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.member
    )

    response = await client.post(
        "/api/v1/users/me/api-keys",
        headers=get_auth_headers(user),
        json={"name": "no", "guild_id": guild.id},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_API_KEYS_REFUSED"


# --- The guild ---------------------------------------------------------------


async def test_a_key_minted_before_the_switch_stops_reaching_the_guild(
    client: AsyncClient, session: AsyncSession
):
    """The answer is decided when the key is used, not when it was made."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.security_admin
    )
    headers = get_auth_headers(admin)
    key_headers = await _key_headers(client, headers, guild_id=guild.id)

    before = await client.get(f"/api/v1/g/{guild.id}/initiatives/", headers=key_headers)
    assert before.status_code == 200

    await client.put(
        f"/api/v1/guilds/{guild.id}/api-access",
        headers=headers,
        json={"allow_api_keys": False},
    )

    after = await client.get(f"/api/v1/g/{guild.id}/initiatives/", headers=key_headers)
    assert after.status_code == 403
    assert after.json()["detail"] == "GUILD_API_KEYS_REFUSED"

    # The same account's own sign-in still reaches it, so what was refused was
    # the credential rather than the membership.
    assert (
        await client.get(f"/api/v1/g/{guild.id}/initiatives/", headers=headers)
    ).status_code == 200


async def test_an_unpinned_key_does_not_reach_a_guild_that_declines_them(
    client: AsyncClient, session: AsyncSession
):
    """A key pinned to no guild addresses every one the account belongs to, so
    the guild's answer cannot rest on what the key names."""
    user = await create_user(session)
    open_guild = await create_guild(session, creator=user)
    closed = await create_guild(session, creator=user, allow_api_keys=False)
    for guild in (open_guild, closed):
        await create_guild_membership(
            session, user=user, guild=guild, role=GuildRole.member
        )
    key_headers = await _key_headers(client, get_auth_headers(user))

    reached = await client.get(
        f"/api/v1/g/{open_guild.id}/initiatives/", headers=key_headers
    )
    assert reached.status_code == 200

    refused = await client.get(
        f"/api/v1/g/{closed.id}/initiatives/", headers=key_headers
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "GUILD_API_KEYS_REFUSED"


async def test_the_cross_guild_aggregate_leaves_out_a_guild_that_declines_keys(
    client: AsyncClient, session: AsyncSession
):
    """``/me/*`` visits each guild itself rather than through the guild path, so
    it drops such a guild rather than being the way around the refusal."""
    user = await create_user(session)
    open_guild = await create_guild(session, creator=user)
    closed = await create_guild(session, creator=user, allow_api_keys=False)
    names = {}
    for guild in (open_guild, closed):
        await create_guild_membership(
            session, user=user, guild=guild, role=GuildRole.member
        )
        initiative = await create_initiative(session, guild, user)
        project = await create_project(session, initiative, user)
        names[guild.id] = project.name

    headers = get_auth_headers(user)
    key_headers = await _key_headers(client, headers)

    by_session = await client.get("/api/v1/me/projects", headers=headers)
    assert {p["name"] for p in by_session.json()["items"]} == set(names.values())

    by_key = await client.get("/api/v1/me/projects", headers=key_headers)
    assert {p["name"] for p in by_key.json()["items"]} == {names[open_guild.id]}
