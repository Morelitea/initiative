"""Where sign-in is configured, and which ways in the deployment permits."""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.models.platform.user import UserRole
from app.testing import (
    create_auth_provider,
    create_federated_identity,
    create_guild,
    create_user,
    get_auth_headers,
    set_auth_scope,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]

SCOPE_URL = "/api/v1/settings/auth/scope"
METHODS_URL = "/api/v1/settings/auth/methods"
READ_URL = "/api/v1/settings/auth/platform"


async def _owner(session: AsyncSession):
    owner = await create_user(session, role=UserRole.owner)
    return owner, get_auth_headers(owner)


async def _require_sign_in(session: AsyncSession, guild_id: int, provider) -> None:
    session.add(
        GuildAuthPolicy(
            guild_id=guild_id,
            policy="required",
            provider_id=provider.id,
            provider_slug=provider.slug,
        )
    )
    await session.commit()


async def test_read_reports_env_posture_until_one_is_chosen(
    client: AsyncClient, session: AsyncSession
):
    """With nothing stored the deploy-time value governs, and the payload says
    so rather than implying somebody chose it."""
    set_auth_scope("guild")
    _, headers = await _owner(session)

    got = await client.get(READ_URL, headers=headers)
    assert got.status_code == 200
    assert got.json()["auth_scope"] == "guild"
    assert got.json()["auth_scope_from_env"] is True
    assert {m["method"] for m in got.json()["methods"]} == {"password", "sso"}
    assert all(m["enabled"] for m in got.json()["methods"])


async def test_choosing_a_posture_pins_it_over_the_env_value(
    client: AsyncClient, session: AsyncSession
):
    """A stored posture governs, and the env value stops being consulted."""
    set_auth_scope("platform")
    _, headers = await _owner(session)

    put = await client.put(SCOPE_URL, headers=headers, json={"auth_scope": "guild"})
    assert put.status_code == 200
    assert put.json()["auth_scope"] == "guild"
    assert put.json()["auth_scope_from_env"] is False

    # The env still says platform; the stored value is what answers.
    set_auth_scope("platform")
    got = await client.get(READ_URL, headers=headers)
    assert got.json()["auth_scope"] == "guild"


async def test_moving_to_platform_posture_waits_for_guild_requirements(
    client: AsyncClient, session: AsyncSession
):
    """A guild requiring a sign-in of its own is reported, with its count, and
    the posture is left as it was. Clearing the requirement releases it."""
    set_auth_scope("guild")
    _, headers = await _owner(session)
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)
    await _require_sign_in(session, guild.id, provider)

    refused = await client.put(
        SCOPE_URL, headers=headers, json={"auth_scope": "platform"}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "SETTINGS_AUTH_SCOPE_GUILD_POLICIES"
    assert refused.headers["X-Affected-Count"] == "1"

    row = await session.get(GuildAuthPolicy, guild.id)
    await session.delete(row)
    await session.commit()

    allowed = await client.put(
        SCOPE_URL, headers=headers, json={"auth_scope": "platform"}
    )
    assert allowed.status_code == 200
    assert allowed.json()["auth_scope"] == "platform"


async def test_moving_to_platform_posture_waits_for_guild_only_sign_ins(
    client: AsyncClient, session: AsyncSession
):
    """An account whose only way in is a guild-scoped provider is reported with
    its count, and the posture is left as it was."""
    set_auth_scope("guild")
    _, headers = await _owner(session)
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    refused = await client.put(
        SCOPE_URL, headers=headers, json={"auth_scope": "platform"}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "SETTINGS_AUTH_SCOPE_WOULD_STRAND"
    assert refused.headers["X-Affected-Count"] == "1"

    got = await client.get(READ_URL, headers=headers)
    assert got.json()["auth_scope"] == "guild"
    assert got.json()["platform_switch_would_strand"] == 1


async def test_moving_to_guild_posture_is_never_refused(
    client: AsyncClient, session: AsyncSession
):
    """Guild posture withdraws no way in — operator-global providers answer in
    both — so the guards that apply in the other direction do not apply here."""
    set_auth_scope("platform")
    _, headers = await _owner(session)
    provider = await create_auth_provider(session, slug="corp")
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    put = await client.put(SCOPE_URL, headers=headers, json={"auth_scope": "guild"})
    assert put.status_code == 200
    assert put.json()["auth_scope"] == "guild"


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


async def test_withdrawing_a_method_signs_nobody_out(
    client: AsyncClient, session: AsyncSession
):
    """Sessions already open keep working; this gates opening a new one."""
    owner, headers = await _owner(session)
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


async def test_both_surfaces_need_the_config_capability(
    client: AsyncClient, session: AsyncSession
):
    member = await create_user(session, role=UserRole.member)
    headers = get_auth_headers(member)

    assert (await client.get(READ_URL, headers=headers)).status_code == 403
    scope = await client.put(SCOPE_URL, headers=headers, json={"auth_scope": "guild"})
    assert scope.status_code == 403
    methods = await client.put(
        METHODS_URL, headers=headers, json={"methods": ["password"]}
    )
    assert methods.status_code == 403
