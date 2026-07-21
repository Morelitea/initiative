"""The operator-global platform OIDC provider — registry-row native.

The ``auth_providers`` row with slug ``oidc`` (``guild_id IS NULL``) is the
**single source of truth** for the platform provider: the settings endpoints
write it directly, the login path and refresh sweep read it, and the client
secret lives in its ``auth_provider_secrets`` companion (write-only, shared
Fernet salt with the retired ``app_settings`` column). The old
reconcile-from-``app_settings`` shim is gone; migration 0153 folded the last
column state into the row and dropped the columns.

``OIDC_*`` env values remain a **first-boot seed only**: when no platform row
exists and the env carries an issuer + client id, :func:`seed_platform_provider_from_env`
creates the row once at startup. After that the row is owned by the settings
UI — the env never overwrites it.

Runs on the system engine (``auth_providers`` / ``auth_provider_secrets``
carry no request-path grants); callers pass their admin session.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.models.platform.auth_provider import AuthProvider, AuthProviderKind

logger = logging.getLogger(__name__)

# Fixed slug for the one platform provider: stable so every caller (login
# path, settings endpoints, refresh sweep) finds the same row. It is also the
# reason the pre-generalization /auth/oidc/* URLs still work — including the
# IdP-registered callback URL.
PLATFORM_OIDC_SLUG = "oidc"

# Presented when no provider row exists yet (mirrors the historical env-seed
# fallback), and used by the env seed when OIDC_SCOPES is unset.
DEFAULT_OIDC_SCOPES = ["openid", "profile", "email", "offline_access"]


def is_login_ready(row: AuthProvider) -> bool:
    """Whether a registry row can serve a login: enabled, OIDC, and carrying
    the non-secret client config discovery needs. The single predicate behind
    the login routes, the provider listing, and guild auth policies."""
    return bool(row.enabled and row.kind == "oidc" and row.issuer and row.client_id)


def scopes_list(row: AuthProvider) -> list[str]:
    """The row's space-joined scopes as the list the settings API speaks."""
    return row.scopes.split() if row.scopes else []


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _join_scopes(scopes: list[str] | None) -> str | None:
    cleaned = [s.strip() for s in (scopes or []) if s and s.strip()]
    return " ".join(cleaned) if cleaned else None


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


async def _create_platform_row(session: AsyncSession, **fields) -> AuthProvider:
    """Insert the platform row; a concurrent-creation race resolves to the
    winner's row (the savepoint keeps the outer transaction usable)."""
    provider = AuthProvider(
        slug=PLATFORM_OIDC_SLUG,
        kind=AuthProviderKind.oidc.value,
        guild_id=None,  # operator-global: platform-level login
        allow_jit=True,  # the platform flow JIT-provisions unknown users
        **fields,
    )
    try:
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


async def upsert_platform_provider(
    session: AsyncSession,
    *,
    enabled: bool,
    issuer: str | None,
    client_id: str | None,
    provider_name: str | None,
    scopes: list[str],
    client_secret: str | None,
) -> AuthProvider:
    """Create or update the platform provider row from the settings surface.

    ``client_secret`` follows the write-only convention: ``None`` keeps the
    stored secret, an empty string clears it, a value replaces it (delegated
    to the shared registry secret helper).
    """
    from app.services.auth.provider_registry import set_provider_secret

    provider = await get_platform_provider(session)
    desired = {
        "display_name": _normalize(provider_name) or "SSO",
        "enabled": bool(enabled),
        "issuer": _normalize(issuer),
        "client_id": _normalize(client_id),
        "scopes": _join_scopes(scopes),
    }
    if provider is None:
        provider = await _create_platform_row(session, **desired)
    else:
        changed = False
        for field, value in desired.items():
            if getattr(provider, field) != value:
                setattr(provider, field, value)
                changed = True
        if changed:
            session.add(provider)
    if client_secret is not None:
        await set_provider_secret(session, provider.id, client_secret)
    await session.commit()
    await session.refresh(provider)
    return provider


async def set_platform_claim_path(
    session: AsyncSession, claim_path: str | None
) -> str | None:
    """Set the platform provider's role-claim path (the OIDC mappings surface).

    A missing platform row is created as a disabled skeleton so the path has a
    home before the provider itself is configured — dormant until the operator
    fills in issuer/client id.
    """
    provider = await get_platform_provider(session)
    cleaned = _normalize(claim_path)
    if provider is None:
        provider = await _create_platform_row(
            session, display_name="SSO", enabled=False, role_claim_path=cleaned
        )
        return provider.role_claim_path
    if provider.role_claim_path != cleaned:
        provider.role_claim_path = cleaned
        session.add(provider)
        await session.commit()
        await session.refresh(provider)
    return provider.role_claim_path


async def seed_platform_provider_from_env(session: AsyncSession) -> bool:
    """First-boot seed: create the platform row from ``OIDC_*`` env values.

    Runs at startup; a no-op unless the env carries an issuer + client id AND
    no platform row exists yet — after creation the settings UI owns the row
    and the env never overwrites it. Returns True when a row was created.
    """
    issuer = _normalize(app_config.OIDC_ISSUER)
    client_id = _normalize(app_config.OIDC_CLIENT_ID)
    if not issuer or not client_id:
        return False
    if await get_platform_provider(session) is not None:
        return False
    scopes = app_config.OIDC_SCOPES or DEFAULT_OIDC_SCOPES
    provider = await upsert_platform_provider(
        session,
        enabled=bool(app_config.OIDC_ENABLED),
        issuer=issuer,
        client_id=client_id,
        provider_name=app_config.OIDC_PROVIDER_NAME,
        scopes=list(scopes),
        client_secret=app_config.OIDC_CLIENT_SECRET or None,
    )
    logger.info(
        "Seeded platform OIDC provider %s from environment (enabled=%s)",
        provider.slug,
        provider.enabled,
    )
    return True
