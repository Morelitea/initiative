"""CRUD tests for the login provider registry admin endpoints."""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_OIDC_CLIENT_SECRET, decrypt_field
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.models.platform.federated_identity import FederatedIdentity
from app.models.platform.user import UserRole
from app.testing.factories import (
    create_auth_provider,
    create_federated_identity,
    create_user,
    get_auth_headers,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]

BASE = "/api/v1/settings/auth/providers/"

_VALID_CREATE = {
    "slug": "corp",
    "display_name": "Corp SSO",
    "issuer": "https://idp.example.com",
    "client_id": "client-123",
    "client_secret": "s3cret-value",
}


async def _owner_headers(session: AsyncSession) -> dict[str, str]:
    owner = await create_user(session, role=UserRole.owner)
    return get_auth_headers(owner)


async def test_owner_creates_provider_secret_write_only(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    response = await client.post(BASE, headers=headers, json=_VALID_CREATE)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["slug"] == "corp"
    assert body["secret_set"] is True
    assert body["reserved"] is False
    assert "client_secret" not in body
    assert "s3cret-value" not in response.text

    row = (
        await session.exec(select(AuthProvider).where(AuthProvider.slug == "corp"))
    ).one()
    secret = await session.get(AuthProviderSecret, row.id)
    assert decrypt_field(secret.client_secret_encrypted, SALT_OIDC_CLIENT_SECRET) == (
        "s3cret-value"
    )


@pytest.mark.parametrize("role", [UserRole.member, UserRole.operator])
async def test_non_owner_tiers_are_refused(
    client: AsyncClient, session: AsyncSession, role: UserRole
):
    """config.manage is owner-only; every verb refuses lower tiers."""
    user = await create_user(session, role=role)
    headers = get_auth_headers(user)
    provider = await create_auth_provider(session)

    assert (await client.get(BASE, headers=headers)).status_code == 403
    assert (
        await client.post(BASE, headers=headers, json=_VALID_CREATE)
    ).status_code == 403
    assert (
        await client.patch(
            f"{BASE}{provider.id}", headers=headers, json={"display_name": "X"}
        )
    ).status_code == 403
    assert (
        await client.delete(f"{BASE}{provider.id}", headers=headers)
    ).status_code == 403


async def test_reserved_slug_is_refused_everywhere(
    client: AsyncClient, session: AsyncSession
):
    """The platform provider is configured via the SSO settings form — this
    CRUD refuses to create, edit, or delete it."""
    headers = await _owner_headers(session)
    platform_row = await create_auth_provider(session, slug="oidc")

    create = await client.post(
        BASE, headers=headers, json={**_VALID_CREATE, "slug": "oidc"}
    )
    assert create.status_code == 400
    assert create.json()["detail"] == "AUTH_PROVIDER_SLUG_RESERVED"

    update = await client.patch(
        f"{BASE}{platform_row.id}", headers=headers, json={"display_name": "X"}
    )
    assert update.status_code == 400
    delete = await client.delete(f"{BASE}{platform_row.id}", headers=headers)
    assert delete.status_code == 400

    listing = await client.get(BASE, headers=headers)
    entries = {e["slug"]: e for e in listing.json()}
    assert entries["oidc"]["reserved"] is True


async def test_duplicate_slug_conflicts(client: AsyncClient, session: AsyncSession):
    headers = await _owner_headers(session)
    await create_auth_provider(session, slug="corp")

    response = await client.post(BASE, headers=headers, json=_VALID_CREATE)
    assert response.status_code == 409
    assert response.json()["detail"] == "AUTH_PROVIDER_SLUG_TAKEN"


async def test_non_https_issuer_rejected(client: AsyncClient, session: AsyncSession):
    headers = await _owner_headers(session)
    response = await client.post(
        BASE,
        headers=headers,
        json={**_VALID_CREATE, "issuer": "http://idp.example.com"},
    )
    assert response.status_code == 422


async def test_update_secret_semantics(client: AsyncClient, session: AsyncSession):
    """client_secret: absent = keep, empty = clear, value = replace."""
    headers = await _owner_headers(session)
    created = await client.post(BASE, headers=headers, json=_VALID_CREATE)
    provider_id = created.json()["id"]

    kept = await client.patch(
        f"{BASE}{provider_id}", headers=headers, json={"display_name": "Renamed"}
    )
    assert kept.status_code == 200
    assert kept.json()["display_name"] == "Renamed"
    assert kept.json()["secret_set"] is True

    replaced = await client.patch(
        f"{BASE}{provider_id}", headers=headers, json={"client_secret": "rotated"}
    )
    assert replaced.json()["secret_set"] is True
    row_id = replaced.json()["id"]
    secret = await session.get(AuthProviderSecret, row_id)
    await session.refresh(secret)
    assert (
        decrypt_field(secret.client_secret_encrypted, SALT_OIDC_CLIENT_SECRET)
        == "rotated"
    )

    cleared = await client.patch(
        f"{BASE}{provider_id}", headers=headers, json={"client_secret": ""}
    )
    assert cleared.json()["secret_set"] is False
    # Clearing removes the companion row rather than leaving an empty one.
    session.expire_all()
    assert await session.get(AuthProviderSecret, provider_id) is None


async def test_update_rejects_explicit_null_on_required_config(
    client: AsyncClient, session: AsyncSession
):
    """An explicit null on issuer/client_id/display_name would leave an
    enabled provider the login flow refuses — rejected at the schema."""
    headers = await _owner_headers(session)
    provider = await create_auth_provider(session)

    for field_name in ("issuer", "client_id", "display_name", "enabled"):
        response = await client.patch(
            f"{BASE}{provider.id}", headers=headers, json={field_name: None}
        )
        assert response.status_code == 422, field_name


async def test_delete_cascades_identity_links(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    provider = await create_auth_provider(session, slug="corp")
    user = await create_user(session)
    await create_federated_identity(session, user, provider=provider)
    provider_id, user_id = provider.id, user.id

    response = await client.delete(f"{BASE}{provider_id}", headers=headers)
    assert response.status_code == 204

    session.expire_all()
    assert (
        await session.exec(select(AuthProvider).where(AuthProvider.slug == "corp"))
    ).one_or_none() is None
    identities = (
        await session.exec(
            select(FederatedIdentity).where(FederatedIdentity.user_id == user_id)
        )
    ).all()
    assert identities == []


async def test_created_provider_reaches_login_page_listing(
    client: AsyncClient, session: AsyncSession
):
    """A CRUD-created, enabled provider is offered by the public login-page
    listing; a disabled one is not."""
    headers = await _owner_headers(session)
    await client.post(BASE, headers=headers, json=_VALID_CREATE)
    await client.post(
        BASE,
        headers=headers,
        json={**_VALID_CREATE, "slug": "dark", "enabled": False},
    )

    listing = await client.get("/api/v1/auth/providers")
    slugs = [p["slug"] for p in listing.json()["providers"]]
    assert "corp" in slugs
    assert "dark" not in slugs
