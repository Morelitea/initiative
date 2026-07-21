"""Guild provider registry: guild-admin CRUD, its gates (posture, guild
admin), and the namespace rules shared with the operator registry."""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.models.platform.guild import GuildRole
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.testing.factories import (
    create_auth_provider,
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
    set_auth_scope,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]

PROVIDER_BODY = {
    "slug": "corp",
    "display_name": "Corp SSO",
    "issuer": "https://idp.example.com",
    "client_id": "corp-client",
}


async def _guild_admin(session: AsyncSession):
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    return admin, guild


async def test_guild_admin_full_crud(client: AsyncClient, session: AsyncSession):
    set_auth_scope()
    admin, guild = await _guild_admin(session)
    headers = get_auth_headers(admin)
    base = f"/api/v1/guilds/{guild.id}/auth/providers"

    created = await client.post(
        base, headers=headers, json={**PROVIDER_BODY, "client_secret": "s3cret"}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["slug"] == "corp"
    assert body["secret_set"] is True
    assert "client_secret" not in body
    provider_id = body["id"]

    listed = await client.get(base, headers=headers)
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()] == [provider_id]

    patched = await client.patch(
        f"{base}/{provider_id}",
        headers=headers,
        json={"display_name": "Corp IdP", "client_secret": ""},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["display_name"] == "Corp IdP"
    assert patched.json()["secret_set"] is False

    deleted = await client.delete(f"{base}/{provider_id}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get(base, headers=headers)).json() == []
    session.expire_all()
    assert await session.get(AuthProvider, provider_id) is None
    assert await session.get(AuthProviderSecret, provider_id) is None


async def test_provider_crud_404_when_guild_auth_disabled(
    client: AsyncClient, session: AsyncSession
):
    """With the operator toggle off, the whole config surface 404s
    (GUILD_AUTH_NOT_ENABLED) — and the guild's existing provider rows are left
    intact, so existing members keep signing in through them."""
    set_auth_scope()
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin, guild_auth_enabled=False)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    # Seed a provider directly (the surface that would create it is closed).
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)
    provider_id = provider.id
    headers = get_auth_headers(admin)
    base = f"/api/v1/guilds/{guild.id}/auth/providers"

    for response in (
        await client.get(base, headers=headers),
        await client.post(base, headers=headers, json=PROVIDER_BODY),
        await client.patch(
            f"{base}/{provider_id}", headers=headers, json={"display_name": "x"}
        ),
        await client.delete(f"{base}/{provider_id}", headers=headers),
    ):
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "GUILD_AUTH_NOT_ENABLED"

    # The provider row survives — maintained, not deleted.
    session.expire_all()
    assert await session.get(AuthProvider, provider_id) is not None


async def test_crud_absent_in_platform_posture(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _guild_admin(session)
    headers = get_auth_headers(admin)
    base = f"/api/v1/guilds/{guild.id}/auth/providers"

    for response in (
        await client.get(base, headers=headers),
        await client.post(base, headers=headers, json=PROVIDER_BODY),
    ):
        assert response.status_code == 404
        assert response.json()["detail"] == "GUILD_AUTH_NOT_ENABLED"


async def test_member_and_non_member_denied(client: AsyncClient, session: AsyncSession):
    set_auth_scope()
    _admin, guild = await _guild_admin(session)
    member = await create_user(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    outsider = await create_user(session)
    base = f"/api/v1/guilds/{guild.id}/auth/providers"

    for user in (member, outsider):
        headers = get_auth_headers(user)
        assert (await client.get(base, headers=headers)).status_code == 403
        assert (
            await client.post(base, headers=headers, json=PROVIDER_BODY)
        ).status_code == 403


async def test_slug_unique_per_guild_not_across_namespaces(
    client: AsyncClient, session: AsyncSession
):
    """A slug is taken only within its own namespace: the same slug can exist
    operator-globally, in guild A, and in guild B at once."""
    set_auth_scope()
    await create_auth_provider(session, slug="corp")  # operator-global
    admin_a, guild_a = await _guild_admin(session)
    admin_b, guild_b = await _guild_admin(session)

    first = await client.post(
        f"/api/v1/guilds/{guild_a.id}/auth/providers",
        headers=get_auth_headers(admin_a),
        json=PROVIDER_BODY,
    )
    assert first.status_code == 201, first.text

    duplicate = await client.post(
        f"/api/v1/guilds/{guild_a.id}/auth/providers",
        headers=get_auth_headers(admin_a),
        json=PROVIDER_BODY,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "AUTH_PROVIDER_SLUG_TAKEN"

    other_guild = await client.post(
        f"/api/v1/guilds/{guild_b.id}/auth/providers",
        headers=get_auth_headers(admin_b),
        json=PROVIDER_BODY,
    )
    assert other_guild.status_code == 201, other_guild.text


async def test_platform_slug_reserved(client: AsyncClient, session: AsyncSession):
    set_auth_scope()
    admin, guild = await _guild_admin(session)

    response = await client.post(
        f"/api/v1/guilds/{guild.id}/auth/providers",
        headers=get_auth_headers(admin),
        json={**PROVIDER_BODY, "slug": "oidc"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "AUTH_PROVIDER_SLUG_RESERVED"


async def test_other_namespace_rows_unreachable(
    client: AsyncClient, session: AsyncSession
):
    """An operator-global row or another guild's row is a 404 through this
    guild's CRUD, for both update and delete."""
    set_auth_scope()
    admin, guild = await _guild_admin(session)
    _admin_b, guild_b = await _guild_admin(session)
    global_row = await create_auth_provider(session, slug="corp")
    foreign_row = await create_auth_provider(session, slug="corp", guild_id=guild_b.id)
    headers = get_auth_headers(admin)
    base = f"/api/v1/guilds/{guild.id}/auth/providers"

    for row_id in (global_row.id, foreign_row.id):
        patched = await client.patch(
            f"{base}/{row_id}", headers=headers, json={"display_name": "X"}
        )
        assert patched.status_code == 404
        assert (
            await client.delete(f"{base}/{row_id}", headers=headers)
        ).status_code == 404


async def test_delete_refused_while_policy_requires(
    client: AsyncClient, session: AsyncSession
):
    set_auth_scope()
    admin, guild = await _guild_admin(session)
    provider = await create_auth_provider(session, slug="corp", guild_id=guild.id)
    session.add(
        GuildAuthPolicy(
            guild_id=guild.id,
            policy="required",
            provider_id=provider.id,
            provider_slug=provider.slug,
        )
    )
    await session.commit()

    response = await client.delete(
        f"/api/v1/guilds/{guild.id}/auth/providers/{provider.id}",
        headers=get_auth_headers(admin),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "AUTH_PROVIDER_IN_USE"
