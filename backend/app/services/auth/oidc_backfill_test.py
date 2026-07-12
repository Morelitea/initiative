"""Tests for the platform-OIDC → provider-registry/identity boot backfill.

The backfill runs on its own ``AdminSessionLocal`` (app_admin) connection, so
setup is committed via the ``session`` fixture first (cross-connection reads are
READ COMMITTED) and assertions read back through it afterward.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.core.encryption import (
    SALT_OIDC_CLIENT_SECRET,
    decrypt_field,
    encrypt_field,
)
from app.models.platform.app_setting import AppSetting
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.models.platform.federated_identity import FederatedIdentity
from app.services.auth.oidc_backfill import backfill_oidc_identity
from app.testing import create_user

pytestmark = [pytest.mark.integration, pytest.mark.database]


async def _configure_oidc(
    session,
    *,
    enabled: bool = True,
    issuer: str | None = None,
    client_secret_ciphertext: str | None = None,
):
    row = (await session.exec(select(AppSetting))).first()
    if row is None:
        row = AppSetting()
        session.add(row)
    row.oidc_enabled = enabled
    row.oidc_issuer = "https://idp.example.com" if issuer is None else issuer
    row.oidc_client_id = "client-123"
    row.oidc_provider_name = "Okta"
    row.oidc_scopes = ["openid", "email"]
    row.oidc_role_claim_path = "roles"
    row.oidc_client_secret_encrypted = client_secret_ciphertext
    await session.commit()
    return row


async def test_backfill_creates_operator_global_provider_and_links(session):
    await _configure_oidc(session)
    u1 = await create_user(session, oidc_sub="sub-alice")
    u2 = await create_user(session, oidc_sub="sub-bob")
    await create_user(session)  # no oidc_sub — must NOT be linked

    summary = await backfill_oidc_identity()

    assert summary.provider_created is True
    assert summary.identities_linked == 2
    assert summary.oidc_users == 2

    provider = (
        await session.exec(select(AuthProvider).where(AuthProvider.slug == "oidc"))
    ).one()
    # The migrated provider MUST stay platform-level (operator-global).
    assert provider.guild_id is None
    assert provider.kind == "oidc"
    assert provider.issuer == "https://idp.example.com"
    assert provider.client_id == "client-123"
    assert provider.scopes == "openid email"
    assert provider.enabled is True

    links = (
        await session.exec(
            select(FederatedIdentity).where(
                FederatedIdentity.provider_id == provider.id
            )
        )
    ).all()
    assert {link.subject for link in links} == {"sub-alice", "sub-bob"}
    assert {link.user_id for link in links} == {u1.id, u2.id}


async def test_backfill_is_idempotent(session):
    ciphertext = encrypt_field("s3cr3t-value", SALT_OIDC_CLIENT_SECRET)
    await _configure_oidc(session, client_secret_ciphertext=ciphertext)
    await create_user(session, oidc_sub="sub-1")

    first = await backfill_oidc_identity()
    second = await backfill_oidc_identity()

    assert first.provider_created is True
    assert first.secret_migrated is True
    assert second.provider_created is False
    assert second.identities_linked == 0  # already linked → ON CONFLICT DO NOTHING
    assert second.secret_migrated is False  # secret already present → no re-copy

    providers = (
        await session.exec(select(AuthProvider).where(AuthProvider.slug == "oidc"))
    ).all()
    assert len(providers) == 1
    links = (await session.exec(select(FederatedIdentity))).all()
    assert len(links) == 1
    # Exactly one secret row, ciphertext unchanged across the re-run.
    secrets = (await session.exec(select(AuthProviderSecret))).all()
    assert len(secrets) == 1
    assert secrets[0].client_secret_encrypted == ciphertext


async def test_backfill_migrates_client_secret_verbatim(session):
    """The client secret lands in the app_admin-only companion, ciphertext moved
    as-is (same Fernet salt) and still decrypting to the original plaintext."""
    ciphertext = encrypt_field("s3cr3t-value", SALT_OIDC_CLIENT_SECRET)
    await _configure_oidc(session, client_secret_ciphertext=ciphertext)

    summary = await backfill_oidc_identity()
    assert summary.secret_migrated is True

    provider = (
        await session.exec(select(AuthProvider).where(AuthProvider.slug == "oidc"))
    ).one()
    secret = (
        await session.exec(
            select(AuthProviderSecret).where(
                AuthProviderSecret.provider_id == provider.id
            )
        )
    ).one()
    # Verbatim: the exact ciphertext string, no decrypt/re-encrypt round trip.
    assert secret.client_secret_encrypted == ciphertext
    # And it still decrypts to the original plaintext under the shared salt.
    assert (
        decrypt_field(secret.client_secret_encrypted, SALT_OIDC_CLIENT_SECRET)
        == "s3cr3t-value"
    )


async def test_backfill_no_secret_row_when_no_client_secret(session):
    """A public / PKCE-only provider (no configured secret) gets a provider row
    but no secret row — the read path treats a missing row as 'no secret'."""
    await _configure_oidc(session, client_secret_ciphertext=None)

    summary = await backfill_oidc_identity()
    assert summary.provider_created is True
    assert summary.secret_migrated is False
    assert (await session.exec(select(AuthProviderSecret))).all() == []


async def test_backfill_disabled_oidc_still_migrates_config(session):
    """A disabled-but-configured provider is still migrated (enabled=false), so
    an operator who toggles it back on keeps their linked identities."""
    await _configure_oidc(session, enabled=False)
    await create_user(session, oidc_sub="sub-x")

    summary = await backfill_oidc_identity()

    assert summary.provider_created is True
    provider = (
        await session.exec(select(AuthProvider).where(AuthProvider.slug == "oidc"))
    ).one()
    assert provider.enabled is False


async def test_backfill_noop_when_oidc_unconfigured(session):
    # No issuer configured; a stray oidc_sub must not link to a phantom provider.
    await _configure_oidc(session, issuer="")
    await create_user(session, oidc_sub="orphan")

    summary = await backfill_oidc_identity()

    assert summary.skipped_reason == "oidc_not_configured"
    assert (await session.exec(select(AuthProvider))).all() == []
    assert (await session.exec(select(FederatedIdentity))).all() == []
