"""Tests for the settings→provider reconcile the login path depends on.

Pins that the provider row always reflects ``app_settings`` at the moment of
use: created on first need, drift folded in on later calls, and the secret
ciphertext mirrored verbatim (including rotation and clearing).
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.models.platform.app_setting import AppSetting
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.services.auth.platform_provider import (
    PLATFORM_OIDC_SLUG,
    ensure_platform_provider,
)

pytestmark = [pytest.mark.integration, pytest.mark.database]


async def _settings(session, **overrides) -> AppSetting:
    row = (await session.exec(select(AppSetting))).first()
    if row is None:
        row = AppSetting()
        session.add(row)
    values = {
        "oidc_enabled": True,
        "oidc_issuer": "https://idp.example.com",
        "oidc_client_id": "client-123",
        "oidc_client_secret_encrypted": "ct-1",
        "oidc_scopes": ["openid", "email"],
        "oidc_provider_name": "Test IdP",
        "oidc_role_claim_path": None,
    }
    values.update(overrides)
    for field, value in values.items():
        setattr(row, field, value)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _secret_ciphertext(session, provider: AuthProvider) -> str | None:
    row = await session.get(AuthProviderSecret, provider.id)
    return row.client_secret_encrypted if row else None


async def test_creates_provider_and_secret_from_settings(session):
    settings_row = await _settings(session)

    provider = await ensure_platform_provider(session, settings_row)

    assert provider.slug == PLATFORM_OIDC_SLUG
    assert provider.guild_id is None
    assert provider.enabled is True
    assert provider.issuer == "https://idp.example.com"
    assert provider.client_id == "client-123"
    assert provider.scopes == "openid email"
    assert provider.display_name == "Test IdP"
    assert provider.allow_jit is True
    assert await _secret_ciphertext(session, provider) == "ct-1"


async def test_reuses_and_reconciles_existing_row(session):
    settings_row = await _settings(session)
    first = await ensure_platform_provider(session, settings_row)

    settings_row = await _settings(
        session, oidc_client_id="client-456", oidc_enabled=False
    )
    second = await ensure_platform_provider(session, settings_row)

    assert second.id == first.id
    assert second.client_id == "client-456"
    assert second.enabled is False
    providers = (
        await session.exec(
            select(AuthProvider).where(AuthProvider.slug == PLATFORM_OIDC_SLUG)
        )
    ).all()
    assert len(providers) == 1


async def test_secret_rotation_is_mirrored(session):
    settings_row = await _settings(session)
    provider = await ensure_platform_provider(session, settings_row)
    assert await _secret_ciphertext(session, provider) == "ct-1"

    settings_row = await _settings(session, oidc_client_secret_encrypted="ct-2")
    provider = await ensure_platform_provider(session, settings_row)
    assert await _secret_ciphertext(session, provider) == "ct-2"


async def test_cleared_secret_clears_companion_row(session):
    settings_row = await _settings(session)
    provider = await ensure_platform_provider(session, settings_row)

    settings_row = await _settings(session, oidc_client_secret_encrypted=None)
    provider = await ensure_platform_provider(session, settings_row)
    assert await _secret_ciphertext(session, provider) is None


async def test_no_secret_creates_no_secret_row(session):
    settings_row = await _settings(session, oidc_client_secret_encrypted=None)
    provider = await ensure_platform_provider(session, settings_row)
    assert await session.get(AuthProviderSecret, provider.id) is None
