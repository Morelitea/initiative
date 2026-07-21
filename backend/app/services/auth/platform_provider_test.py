"""Tests for the registry-native platform provider service.

Pins that the ``auth_providers`` row with the platform slug is the single
source of truth: the settings upsert creates and updates it (write-only
secret semantics included), the claim-path setter targets it, and the env
seed creates it exactly once on a fresh install.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.core.encryption import SALT_OIDC_CLIENT_SECRET, decrypt_field
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.services.auth.platform_provider import (
    PLATFORM_OIDC_SLUG,
    get_platform_provider,
    seed_platform_provider_from_env,
    set_platform_claim_path,
    upsert_platform_provider,
)

pytestmark = [pytest.mark.integration, pytest.mark.database]


async def _upsert(session, **overrides) -> AuthProvider:
    values = {
        "enabled": True,
        "issuer": "https://idp.example.com",
        "client_id": "client-123",
        "provider_name": "Test IdP",
        "scopes": ["openid", "email"],
        "client_secret": "s3cret-1",
    }
    values.update(overrides)
    return await upsert_platform_provider(session, **values)


async def _secret_plaintext(session, provider: AuthProvider) -> str | None:
    row = await session.get(AuthProviderSecret, provider.id)
    if row is None or not row.client_secret_encrypted:
        return None
    return decrypt_field(row.client_secret_encrypted, SALT_OIDC_CLIENT_SECRET)


async def test_upsert_creates_provider_and_secret(session):
    provider = await _upsert(session)

    assert provider.slug == PLATFORM_OIDC_SLUG
    assert provider.guild_id is None
    assert provider.enabled is True
    assert provider.issuer == "https://idp.example.com"
    assert provider.client_id == "client-123"
    assert provider.scopes == "openid email"
    assert provider.display_name == "Test IdP"
    assert provider.allow_jit is True
    assert await _secret_plaintext(session, provider) == "s3cret-1"


async def test_upsert_updates_existing_row_in_place(session):
    first = await _upsert(session)

    second = await _upsert(session, client_id="client-456", enabled=False)

    assert second.id == first.id
    assert second.client_id == "client-456"
    assert second.enabled is False
    providers = (
        await session.exec(
            select(AuthProvider).where(AuthProvider.slug == PLATFORM_OIDC_SLUG)
        )
    ).all()
    assert len(providers) == 1


async def test_secret_write_only_semantics(session):
    """None keeps the stored secret, empty clears it, a value replaces it."""
    provider = await _upsert(session)
    assert await _secret_plaintext(session, provider) == "s3cret-1"

    provider = await _upsert(session, client_secret=None)
    assert await _secret_plaintext(session, provider) == "s3cret-1"

    provider = await _upsert(session, client_secret="s3cret-2")
    assert await _secret_plaintext(session, provider) == "s3cret-2"

    provider = await _upsert(session, client_secret="")
    assert await _secret_plaintext(session, provider) is None


async def test_empty_provider_name_falls_back(session):
    provider = await _upsert(session, provider_name="  ")
    assert provider.display_name == "SSO"


async def test_claim_path_targets_provider_row(session):
    await _upsert(session)

    assert await set_platform_claim_path(session, " groups ") == "groups"
    provider = await get_platform_provider(session)
    assert provider.role_claim_path == "groups"

    assert await set_platform_claim_path(session, None) is None
    provider = await get_platform_provider(session)
    assert provider.role_claim_path is None


async def test_claim_path_creates_dormant_skeleton(session):
    """Setting a claim path before the provider is configured creates a
    disabled skeleton row to carry it — dormant until configured."""
    assert await get_platform_provider(session) is None

    assert await set_platform_claim_path(session, "roles") == "roles"

    provider = await get_platform_provider(session)
    assert provider is not None
    assert provider.enabled is False
    assert provider.issuer is None
    assert provider.role_claim_path == "roles"


async def test_env_seed_creates_row_once(session, monkeypatch):
    from app.core.config import settings as app_config

    monkeypatch.setattr(app_config, "OIDC_ISSUER", "https://env-idp.example.com")
    monkeypatch.setattr(app_config, "OIDC_CLIENT_ID", "env-client")
    monkeypatch.setattr(app_config, "OIDC_CLIENT_SECRET", "env-secret")
    monkeypatch.setattr(app_config, "OIDC_ENABLED", True)
    monkeypatch.setattr(app_config, "OIDC_PROVIDER_NAME", "Env SSO")
    monkeypatch.setattr(app_config, "OIDC_SCOPES", ["openid", "profile"])

    assert await seed_platform_provider_from_env(session) is True
    provider = await get_platform_provider(session)
    assert provider.issuer == "https://env-idp.example.com"
    assert provider.client_id == "env-client"
    assert provider.enabled is True
    assert provider.display_name == "Env SSO"
    assert provider.scopes == "openid profile"
    assert await _secret_plaintext(session, provider) == "env-secret"

    # Second boot: the row exists — the env never overwrites it.
    monkeypatch.setattr(app_config, "OIDC_CLIENT_ID", "changed-client")
    assert await seed_platform_provider_from_env(session) is False
    provider = await get_platform_provider(session)
    assert provider.client_id == "env-client"


async def test_env_seed_noop_without_config(session, monkeypatch):
    from app.core.config import settings as app_config

    monkeypatch.setattr(app_config, "OIDC_ISSUER", None)
    monkeypatch.setattr(app_config, "OIDC_CLIENT_ID", None)

    assert await seed_platform_provider_from_env(session) is False
    assert await get_platform_provider(session) is None
