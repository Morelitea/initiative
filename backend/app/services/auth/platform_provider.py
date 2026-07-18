"""Reconcile the operator-global OIDC provider row from ``app_settings``.

Until the provider registry gets its own CRUD, ``app_settings.oidc_*`` — the
admin settings UI — remains the operator's source of truth for the platform
provider. The login path resolves identities against the ``auth_providers``
row, so the two must agree: :func:`ensure_platform_provider` get-or-creates
the row and folds in any drift (issuer, client_id, scopes, a rotated secret)
whenever the login path asks for the provider. Reconcile-on-read keeps a
settings edit effective immediately, without waiting for a reboot.

The client secret ciphertext moves **verbatim** — ``app_settings`` and
``auth_provider_secrets`` share the same Fernet salt, so there is no
decrypt/re-encrypt round trip.

Runs on the system engine (``auth_providers`` / ``auth_provider_secrets`` are
app_admin surfaces); callers pass their admin session.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.app_setting import AppSetting
from app.models.platform.auth_provider import AuthProvider, AuthProviderKind
from app.models.platform.auth_provider_secret import AuthProviderSecret

logger = logging.getLogger(__name__)

# Fixed slug for the one platform provider: stable so every caller (boot
# backfill, login path) finds the same row.
PLATFORM_OIDC_SLUG = "oidc"


def is_login_ready(row: AuthProvider) -> bool:
    """Whether a registry row can serve a login: enabled, OIDC, and carrying
    the non-secret client config discovery needs. The single predicate behind
    the login routes, the provider listing, and guild auth policies."""
    return bool(row.enabled and row.kind == "oidc" and row.issuer and row.client_id)


async def get_platform_provider(session: AsyncSession) -> AuthProvider | None:
    """The operator-global (``guild_id IS NULL``) platform provider row."""
    return (
        await session.exec(
            select(AuthProvider).where(
                AuthProvider.slug == PLATFORM_OIDC_SLUG,
                AuthProvider.guild_id.is_(None),
            )
        )
    ).first()


async def ensure_platform_provider(
    session: AsyncSession, settings_row: AppSetting
) -> AuthProvider:
    """Get-or-create the platform provider row, reconciled with ``app_settings``.

    Caller must have checked that OIDC is configured (``oidc_issuer`` and
    ``oidc_client_id`` set). Commits only when something actually changed;
    concurrent creation races resolve to the winner's row.
    """
    provider = await get_platform_provider(session)
    if provider is None:
        provider = await _create_provider(session, settings_row)

    changed = _apply_settings(provider, settings_row)
    if changed:
        session.add(provider)
    secret_changed = await _reconcile_secret(session, provider, settings_row)
    if changed or secret_changed:
        await session.commit()
        await session.refresh(provider)
    return provider


async def _create_provider(
    session: AsyncSession, settings_row: AppSetting
) -> AuthProvider:
    provider = AuthProvider(
        slug=PLATFORM_OIDC_SLUG,
        display_name=settings_row.oidc_provider_name or "SSO",
        kind=AuthProviderKind.oidc.value,
        enabled=bool(settings_row.oidc_enabled),
        guild_id=None,  # operator-global: platform-level login
        issuer=settings_row.oidc_issuer,
        client_id=settings_row.oidc_client_id,
        scopes=_scopes_string(settings_row),
        role_claim_path=settings_row.oidc_role_claim_path,
        allow_jit=True,  # the platform flow JIT-provisions unknown users
    )
    try:
        # Savepoint so losing a concurrent-creation race leaves the outer
        # transaction usable for the recovery read (the _provision pattern).
        async with session.begin_nested():
            session.add(provider)
            await session.flush()
        await session.commit()
        await session.refresh(provider)
        return provider
    except IntegrityError:
        winner = await get_platform_provider(session)
        if winner is None:  # pragma: no cover - the conflict implies a winner
            raise
        return winner


def _scopes_string(settings_row: AppSetting) -> str | None:
    scopes = settings_row.oidc_scopes or []
    return " ".join(scopes) if scopes else None


def _apply_settings(provider: AuthProvider, settings_row: AppSetting) -> bool:
    """Fold ``app_settings`` values into the provider row; True if drifted."""
    desired = {
        "display_name": settings_row.oidc_provider_name or "SSO",
        "enabled": bool(settings_row.oidc_enabled),
        "issuer": settings_row.oidc_issuer,
        "client_id": settings_row.oidc_client_id,
        "scopes": _scopes_string(settings_row),
        "role_claim_path": settings_row.oidc_role_claim_path,
    }
    changed = False
    for field, value in desired.items():
        if getattr(provider, field) != value:
            setattr(provider, field, value)
            changed = True
    return changed


async def _reconcile_secret(
    session: AsyncSession, provider: AuthProvider, settings_row: AppSetting
) -> bool:
    """Mirror the settings secret ciphertext into ``auth_provider_secrets``.

    A changed ciphertext (rotation, or a re-save — Fernet output is fresh per
    encryption) is copied over; a cleared settings secret clears the companion
    row's value (public / PKCE-only client). Returns True if a write is staged.
    """
    ciphertext = settings_row.oidc_client_secret_encrypted
    secret_row = await session.get(AuthProviderSecret, provider.id)
    if secret_row is None:
        if ciphertext is None:
            return False
        secret_row = AuthProviderSecret(
            provider_id=provider.id, client_secret_encrypted=ciphertext
        )
        try:
            async with session.begin_nested():
                session.add(secret_row)
                await session.flush()
        except IntegrityError:
            # A concurrent login created it; reconcile that row instead.
            winner = await session.get(AuthProviderSecret, provider.id)
            if winner is None:  # pragma: no cover - the conflict implies a winner
                raise
            if winner.client_secret_encrypted != ciphertext:
                winner.client_secret_encrypted = ciphertext
                session.add(winner)
                return True
            return False
        return True
    if secret_row.client_secret_encrypted != ciphertext:
        secret_row.client_secret_encrypted = ciphertext
        session.add(secret_row)
        return True
    return False
