"""Which ways in the deployment permits."""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import UserRole
from app.testing import (
    create_auth_provider,
    create_federated_identity,
    create_guild,
    create_guild_auth_policy,
    create_user,
    get_auth_headers,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]

METHODS_URL = "/api/v1/settings/auth/methods"
READ_URL = "/api/v1/settings/auth/platform"


async def _owner(session: AsyncSession):
    owner = await create_user(session, role=UserRole.owner)
    return owner, get_auth_headers(owner)


async def test_read_reports_every_method_and_its_cost(
    client: AsyncClient, session: AsyncSession
):
    """Both methods are listed whether or not they are on, each with the number
    withdrawing it would concern."""
    _, headers = await _owner(session)

    got = await client.get(READ_URL, headers=headers)
    assert got.status_code == 200
    assert {m["method"] for m in got.json()["methods"]} == {"password", "sso"}
    assert all(m["enabled"] for m in got.json()["methods"])
    assert got.json()["guilds_requiring_sign_in"] == 0


async def test_at_least_one_way_in_must_remain(
    client: AsyncClient, session: AsyncSession
):
    _, headers = await _owner(session)
    put = await client.put(METHODS_URL, headers=headers, json={"methods": []})
    assert put.status_code == 422


async def test_withdrawing_a_method_reports_who_it_strands(
    client: AsyncClient, session: AsyncSession
):
    """Withdrawing SSO while an account signs in only that way is reported with
    the count, and proceeds when the caller echoes that exact number."""
    _, headers = await _owner(session)
    provider = await create_auth_provider(session, slug="corp")
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    refused = await client.put(
        METHODS_URL, headers=headers, json={"methods": ["password"]}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHODS_WOULD_STRAND"
    assert refused.headers["X-Affected-Count"] == "1"

    stale = await client.put(
        METHODS_URL,
        headers=headers,
        json={"methods": ["password"], "acknowledge_stranded": 99},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "SETTINGS_LOGIN_METHODS_STALE_ACK"

    accepted = await client.put(
        METHODS_URL,
        headers=headers,
        json={"methods": ["password"], "acknowledge_stranded": 1},
    )
    assert accepted.status_code == 200
    enabled = {m["method"] for m in accepted.json()["methods"] if m["enabled"]}
    assert enabled == {"password"}


async def test_withdrawing_sso_waits_for_guild_requirements(
    client: AsyncClient, session: AsyncSession
):
    """A guild requiring a sign-in through a provider of its own is reported
    with its count. A requirement is enforced from its policy row and stands on
    its own, so it is lifted first and the withdrawal then goes through."""
    _, headers = await _owner(session)
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)
    policy = await create_guild_auth_policy(session, guild, provider)

    refused = await client.put(
        METHODS_URL, headers=headers, json={"methods": ["password"]}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHODS_GUILD_POLICIES"
    assert refused.headers["X-Affected-Count"] == "1"

    got = await client.get(READ_URL, headers=headers)
    assert got.json()["guilds_requiring_sign_in"] == 1

    await session.delete(policy)
    await session.commit()

    allowed = await client.put(
        METHODS_URL, headers=headers, json={"methods": ["password"]}
    )
    assert allowed.status_code == 200


async def test_a_guild_only_identity_is_counted_when_sso_is_withdrawn(
    client: AsyncClient, session: AsyncSession
):
    """Withdrawing single sign-on closes the guild-addressed login route as
    well as the platform one, so an account reached only through a guild's
    provider is one the count has to report."""
    _, headers = await _owner(session)
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="guild", guild_id=guild.id)
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    refused = await client.put(
        METHODS_URL, headers=headers, json={"methods": ["password"]}
    )

    assert refused.status_code == 409
    assert refused.headers["X-Affected-Count"] == "1"


async def test_withdrawing_a_method_nobody_uses_needs_no_acknowledgement(
    client: AsyncClient, session: AsyncSession
):
    _, headers = await _owner(session)
    put = await client.put(METHODS_URL, headers=headers, json={"methods": ["password"]})
    assert put.status_code == 200
    enabled = {m["method"] for m in put.json()["methods"] if m["enabled"]}
    assert enabled == {"password"}


async def test_withdrawing_sso_closes_the_provider_routes(
    client: AsyncClient, session: AsyncSession
):
    """Server-side, not merely hidden: the listing empties and the login route
    refuses."""
    _, headers = await _owner(session)
    await create_auth_provider(session, slug="corp")

    listed = await client.get("/api/v1/auth/providers")
    assert any(p["slug"] == "corp" for p in listed.json()["providers"])

    put = await client.put(METHODS_URL, headers=headers, json={"methods": ["password"]})
    assert put.status_code == 200

    assert (await client.get("/api/v1/auth/providers")).json()["providers"] == []
    login = await client.get("/api/v1/auth/corp/login", follow_redirects=False)
    assert login.status_code == 404


async def test_withdrawing_sso_closes_a_guilds_provider_routes_too(
    client: AsyncClient, session: AsyncSession
):
    """The guild-addressed listing and login go with it."""
    _, headers = await _owner(session)
    guild = await create_guild(session)
    await create_auth_provider(session, slug="corp", guild_id=guild.id)

    listed = await client.get(f"/api/v1/auth/g/{guild.id}/providers")
    assert any(p["slug"] == "corp" for p in listed.json()["providers"])

    put = await client.put(METHODS_URL, headers=headers, json={"methods": ["password"]})
    assert put.status_code == 200

    after = await client.get(f"/api/v1/auth/g/{guild.id}/providers")
    assert after.json()["providers"] == []
    login = await client.get(
        f"/api/v1/auth/g/{guild.id}/corp/login", follow_redirects=False
    )
    assert login.status_code == 404


async def test_withdrawing_password_closes_its_routes(
    client: AsyncClient, session: AsyncSession
):
    """The sign-in, the registration that mints one, and both halves of reset."""
    _, headers = await _owner(session)
    provider = await create_auth_provider(session, slug="corp")
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    put = await client.put(
        METHODS_URL,
        headers=headers,
        json={"methods": ["sso"], "acknowledge_stranded": 1},
    )
    assert put.status_code == 200

    token = await client.post(
        "/api/v1/auth/token",
        data={"username": "someone@example.com", "password": "whatever"},
    )
    assert token.status_code == 403
    assert token.json()["detail"] == "SETTINGS_LOGIN_METHOD_NOT_PERMITTED"

    register = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "new@example.com",
            "username": "newperson",
            "password": "a-long-enough-password-1",
            "full_name": "New Person",
        },
    )
    assert register.status_code == 403

    forgot = await client.post(
        "/api/v1/auth/password/forgot", json={"email": "someone@example.com"}
    )
    assert forgot.status_code == 403


async def test_an_account_with_only_a_guild_provider_counts_as_signed_in(
    client: AsyncClient, session: AsyncSession
):
    """A guild-scoped provider answers logins, so an account holding only one
    is not counted as stranded by withdrawing the password."""
    owner, headers = await _owner(session)
    guild = await create_guild(session, creator=owner)
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)

    before = await client.get(READ_URL, headers=headers)
    baseline = next(m for m in before.json()["methods"] if m["method"] == "password")[
        "would_strand"
    ]

    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    after = await client.get(READ_URL, headers=headers)
    password = next(m for m in after.json()["methods"] if m["method"] == "password")
    # A guild-scoped provider answers logins, so the member it linked is a way
    # in rather than an account the password is holding up.
    assert password["would_strand"] == baseline


async def test_withdrawing_a_method_signs_nobody_out(
    client: AsyncClient, session: AsyncSession
):
    """Sessions already open keep working; this gates opening a new one."""
    _, headers = await _owner(session)
    provider = await create_auth_provider(session, slug="corp")
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    put = await client.put(
        METHODS_URL,
        headers=headers,
        json={"methods": ["sso"], "acknowledge_stranded": 1},
    )
    assert put.status_code == 200

    still_in = await client.get(READ_URL, headers=headers)
    assert still_in.status_code == 200


async def test_the_surface_needs_the_config_capability(
    client: AsyncClient, session: AsyncSession
):
    member = await create_user(session, role=UserRole.member)
    headers = get_auth_headers(member)

    assert (await client.get(READ_URL, headers=headers)).status_code == 403
    methods = await client.put(
        METHODS_URL, headers=headers, json={"methods": ["password"]}
    )
    assert methods.status_code == 403


async def test_withdrawing_sso_counts_a_guild_that_requires_a_method(
    client: AsyncClient, session: AsyncSession
):
    """A requirement can name a way in rather than a provider, and the guard
    that holds single sign-on back has to see both kinds."""
    from app.models.platform.guild_auth_policy import GuildAuthPolicy

    _, headers = await _owner(session)
    guild = await create_guild(session)
    session.add(
        GuildAuthPolicy(guild_id=guild.id, policy="required", require_methods=["sso"])
    )
    await session.commit()

    refused = await client.put(
        METHODS_URL, headers=headers, json={"methods": ["password"]}
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHODS_GUILD_POLICIES"
    assert refused.headers["X-Affected-Count"] == "1"
