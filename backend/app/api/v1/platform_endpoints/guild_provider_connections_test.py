"""What a community can say about who signs in, and what it cannot.

The shape under test: **the operator holds providers, a community connects to
one.** So nothing here takes an issuer, a client id or a secret, a community
sees only the providers it is allowed to, and the narrowing it sets is what
decides whether somebody arriving is one of theirs.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import AuthProviderMessages
from app.models.platform.guild import GuildRole
from app.testing.factories import (
    create_auth_provider,
    create_guild,
    create_guild_membership,
    create_guild_provider_connection,
    create_user,
    get_auth_headers,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]


async def _seat(session: AsyncSession, *, auth_options: list[str] | None = None):
    """A community with somebody in the seat that decides who may enter."""
    admin = await create_user(session)
    kwargs = {} if auth_options is None else {"auth_options": auth_options}
    guild = await create_guild(session, creator=admin, **kwargs)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.superadmin
    )
    return admin, guild


def _base(guild_id: int) -> str:
    return f"/api/v1/guilds/{guild_id}/auth/connections"


async def test_the_seat_connects_narrows_and_disconnects(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await create_auth_provider(
        session, slug="google", display_name="Google", connectable_by_guilds=True
    )
    headers = get_auth_headers(admin)

    created = await client.post(
        _base(guild.id),
        headers=headers,
        json={"provider_id": provider.id, "claim": "hd", "claim_values": ["morels.me"]},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["provider_display_name"] == "Google"
    assert body["claim"] == "hd"
    assert body["claim_values"] == ["morels.me"]
    # Nothing about the provider's internals comes back on a community's
    # surface, because a community holds none of it.
    assert "issuer" not in body
    assert "client_id" not in body

    listed = await client.get(_base(guild.id), headers=headers)
    assert [row["provider_slug"] for row in listed.json()] == ["google"]

    narrowed = await client.patch(
        f"{_base(guild.id)}/{body['id']}",
        headers=headers,
        json={"claim_values": ["morels.me", "morels.dev"]},
    )
    assert narrowed.status_code == 200, narrowed.text
    assert narrowed.json()["claim_values"] == ["morels.me", "morels.dev"]

    gone = await client.delete(f"{_base(guild.id)}/{body['id']}", headers=headers)
    assert gone.status_code == 204, gone.text
    assert await client.get(_base(guild.id), headers=headers) is not None
    assert (await client.get(_base(guild.id), headers=headers)).json() == []


async def test_a_community_sees_what_is_offered_and_what_it_already_uses(
    client: AsyncClient, session: AsyncSession
):
    """The picker is the providers on offer plus the ones already connected —
    which is what keeps a provider registered for one customer out of every
    other customer's list."""
    admin, guild = await _seat(session)
    offered = await create_auth_provider(
        session, slug="google", display_name="Google", connectable_by_guilds=True
    )
    theirs = await create_auth_provider(
        session, slug="acme-okta", display_name="Acme Okta"
    )
    somebody_elses = await create_auth_provider(
        session, slug="beta-okta", display_name="Beta Okta"
    )
    await create_guild_provider_connection(session, guild=guild, provider=theirs)
    _, other_guild = await _seat(session)
    await create_guild_provider_connection(
        session, guild=other_guild, provider=somebody_elses
    )

    response = await client.get(
        f"{_base(guild.id)}/available", headers=get_auth_headers(admin)
    )

    assert response.status_code == 200, response.text
    names = {row["display_name"] for row in response.json()}
    assert names == {"Google", "Acme Okta"}
    assert "Beta Okta" not in names
    assert offered.id in {row["id"] for row in response.json()}


async def test_a_community_cannot_connect_to_one_it_was_never_offered(
    client: AsyncClient, session: AsyncSession
):
    """The write is held to the same rule the picker lists by, so a guessed id
    gets no further than a name the community was never shown."""
    admin, guild = await _seat(session)
    somebody_elses = await create_auth_provider(session, slug="beta-okta")

    response = await client.post(
        _base(guild.id),
        headers=get_auth_headers(admin),
        json={"provider_id": somebody_elses.id},
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == AuthProviderMessages.NOT_FOUND


async def test_a_narrowing_is_both_halves_or_neither(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await create_auth_provider(
        session, slug="google", connectable_by_guilds=True
    )
    headers = get_auth_headers(admin)

    # A narrowing is both halves or neither; half of one narrows nothing.
    half = await client.post(
        _base(guild.id),
        headers=headers,
        json={"provider_id": provider.id, "claim": "hd", "claim_values": []},
    )
    assert half.status_code == 422, half.text
    assert half.json()["detail"] == AuthProviderMessages.CONNECTION_HALF_NARROWED

    # Neither half is the unnarrowed connection, which is allowed.
    whole = await client.post(
        _base(guild.id), headers=headers, json={"provider_id": provider.id}
    )
    assert whole.status_code == 201, whole.text
    assert whole.json()["claim"] is None


async def test_a_community_connects_to_a_provider_once(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await create_auth_provider(
        session, slug="google", connectable_by_guilds=True
    )
    await create_guild_provider_connection(session, guild=guild, provider=provider)

    again = await client.post(
        _base(guild.id),
        headers=get_auth_headers(admin),
        json={"provider_id": provider.id},
    )

    # Two narrowings of one provider would be two answers to one question.
    assert again.status_code == 409, again.text
    assert again.json()["detail"] == AuthProviderMessages.CONNECTION_EXISTS


async def test_an_ordinary_admin_reads_but_does_not_connect(
    client: AsyncClient, session: AsyncSession
):
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    provider = await create_auth_provider(
        session, slug="google", connectable_by_guilds=True
    )
    headers = get_auth_headers(admin)

    assert (await client.get(_base(guild.id), headers=headers)).status_code == 200
    refused = await client.post(
        _base(guild.id), headers=headers, json={"provider_id": provider.id}
    )
    assert refused.status_code == 403, refused.text


async def test_the_surface_404s_when_the_option_is_not_granted(
    client: AsyncClient, session: AsyncSession
):
    """Without the operator's grant the whole surface 404s — and the
    connections a community already has are left intact, so its members keep
    signing in through them."""
    admin, guild = await _seat(session, auth_options=[])
    provider = await create_auth_provider(session, slug="google")
    connection = await create_guild_provider_connection(
        session, guild=guild, provider=provider
    )
    headers = get_auth_headers(admin)

    assert (await client.get(_base(guild.id), headers=headers)).status_code == 404
    assert (
        await client.get(f"{_base(guild.id)}/available", headers=headers)
    ).status_code == 404
    assert (
        await client.delete(f"{_base(guild.id)}/{connection.id}", headers=headers)
    ).status_code == 404


async def test_one_communitys_connection_is_not_anothers_to_change(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    _, other_guild = await _seat(session)
    provider = await create_auth_provider(session, slug="google")
    theirs = await create_guild_provider_connection(
        session, guild=other_guild, provider=provider
    )

    response = await client.patch(
        f"{_base(guild.id)}/{theirs.id}",
        headers=get_auth_headers(admin),
        json={"enabled": False},
    )

    # Somebody else's is indistinguishable from one that is not there.
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == AuthProviderMessages.CONNECTION_NOT_FOUND
