"""Who may look a provider up, and what the answer carries.

The looking-up itself is covered in ``app/services/auth/provider_probe_test.py``;
these are the gates, the shape of the response, and the namespace boundary.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import AuthProviderMessages
from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.services.auth import provider_probe
from app.testing.factories import (
    create_auth_provider,
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)
from app.testing.oidc import ISSUER, FakeIdp

pytestmark = [pytest.mark.integration, pytest.mark.auth]

OPERATOR_BASE = "/api/v1/settings/auth/providers"


@pytest.fixture
def fake_idp(monkeypatch: pytest.MonkeyPatch) -> FakeIdp:
    """Point the probe's own discovery client at a fake provider.

    Patched at ``fresh_discovery``, which is where the service builds it, so
    the endpoints are exercised exactly as they ship.
    """
    idp = FakeIdp()
    monkeypatch.setattr(
        provider_probe,
        "fresh_discovery",
        lambda **_: provider_probe.OidcDiscovery(
            cache_ttl_seconds=0, client_factory=idp.client_factory()
        ),
    )
    return idp


async def _owner_headers(session: AsyncSession) -> dict[str, str]:
    owner = await create_user(session, role=UserRole.owner)
    return get_auth_headers(owner)


async def _security_admin(session: AsyncSession):
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.security_admin
    )
    return admin, guild


# ── The operator's registry ────────────────────────────────────────────────


async def test_discover_reports_what_the_address_offers(
    client: AsyncClient, session: AsyncSession, fake_idp: FakeIdp
):
    fake_idp.discovery_doc["scopes_supported"] = ["openid", "email", "groups"]
    fake_idp.discovery_doc["claims_supported"] = ["sub", "groups"]
    headers = await _owner_headers(session)

    response = await client.post(
        f"{OPERATOR_BASE}/discover", headers=headers, json={"issuer": ISSUER}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["issuer"] == ISSUER
    assert body["token_endpoint"] == f"{ISSUER}/token"
    assert body["scopes_supported"] == ["openid", "email", "groups"]
    assert body["claims_supported"] == ["sub", "groups"]


async def test_discover_refuses_a_non_https_address(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)

    response = await client.post(
        f"{OPERATOR_BASE}/discover",
        headers=headers,
        json={"issuer": "http://idp.example.com"},
    )

    # Turned away at the schema, the same rule the issuer field already holds.
    assert response.status_code == 422, response.text


async def test_discover_reports_a_mismatch_as_a_code(
    client: AsyncClient, session: AsyncSession, fake_idp: FakeIdp
):
    fake_idp.discovery_doc["issuer"] = "https://somewhere-else.example.com"
    headers = await _owner_headers(session)

    response = await client.post(
        f"{OPERATOR_BASE}/discover", headers=headers, json={"issuer": ISSUER}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["error_code"] == AuthProviderMessages.DISCOVERY_ISSUER_MISMATCH
    # The address it actually named is not handed back.
    assert body["issuer"] is None


@pytest.mark.parametrize("role", [UserRole.member, UserRole.operator])
async def test_discover_needs_config_manage(
    client: AsyncClient, session: AsyncSession, role: UserRole
):
    user = await create_user(session, role=role)

    response = await client.post(
        f"{OPERATOR_BASE}/discover",
        headers=get_auth_headers(user),
        json={"issuer": ISSUER},
    )

    assert response.status_code == 403, response.text


async def test_test_uses_the_stored_issuer(
    client: AsyncClient, session: AsyncSession, fake_idp: FakeIdp
):
    provider = await create_auth_provider(session, slug="corp")
    headers = await _owner_headers(session)

    response = await client.post(f"{OPERATOR_BASE}/{provider.id}/test", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert fake_idp.calls.count("/.well-known/openid-configuration") == 1


async def test_test_404s_for_a_provider_that_is_not_there(
    client: AsyncClient, session: AsyncSession, fake_idp: FakeIdp
):
    headers = await _owner_headers(session)

    response = await client.post(f"{OPERATOR_BASE}/9999/test", headers=headers)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == AuthProviderMessages.NOT_FOUND


async def test_the_operator_registry_cannot_test_a_guild_row(
    client: AsyncClient, session: AsyncSession, fake_idp: FakeIdp
):
    admin, guild = await _security_admin(session)
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)
    headers = await _owner_headers(session)

    response = await client.post(f"{OPERATOR_BASE}/{provider.id}/test", headers=headers)

    # A row from the other namespace is indistinguishable from a missing one.
    assert response.status_code == 404, response.text


# ── A community's own registry ─────────────────────────────────────────────


async def test_the_seat_may_discover_and_test(
    client: AsyncClient, session: AsyncSession, fake_idp: FakeIdp
):
    admin, guild = await _security_admin(session)
    headers = get_auth_headers(admin)
    base = f"/api/v1/guilds/{guild.id}/auth/providers"
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)

    discovered = await client.post(
        f"{base}/discover", headers=headers, json={"issuer": ISSUER}
    )
    assert discovered.status_code == 200, discovered.text
    assert discovered.json()["ok"] is True

    tested = await client.post(f"{base}/{provider.id}/test", headers=headers)
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] is True


async def test_an_ordinary_admin_may_not_look_a_provider_up(
    client: AsyncClient, session: AsyncSession, fake_idp: FakeIdp
):
    """Reading the registry is an admin's; looking one up goes with changing
    it — the answer fills in a form only the seat may save."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    headers = get_auth_headers(admin)
    base = f"/api/v1/guilds/{guild.id}/auth/providers"

    response = await client.post(
        f"{base}/discover", headers=headers, json={"issuer": ISSUER}
    )

    assert response.status_code == 403, response.text


async def test_looking_up_404s_when_the_option_is_not_granted(
    client: AsyncClient, session: AsyncSession, fake_idp: FakeIdp
):
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin, auth_options=[])
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.security_admin
    )
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)
    headers = get_auth_headers(admin)
    base = f"/api/v1/guilds/{guild.id}/auth/providers"

    discovered = await client.post(
        f"{base}/discover", headers=headers, json={"issuer": ISSUER}
    )
    tested = await client.post(f"{base}/{provider.id}/test", headers=headers)

    assert discovered.status_code == 404, discovered.text
    assert tested.status_code == 404, tested.text


async def test_a_guild_cannot_test_another_guilds_provider(
    client: AsyncClient, session: AsyncSession, fake_idp: FakeIdp
):
    admin, guild = await _security_admin(session)
    _, other_guild = await _security_admin(session)
    theirs = await create_auth_provider(session, slug="corp", guild_id=other_guild.id)

    response = await client.post(
        f"/api/v1/guilds/{guild.id}/auth/providers/{theirs.id}/test",
        headers=get_auth_headers(admin),
    )

    assert response.status_code == 404, response.text
