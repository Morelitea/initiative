"""Boot backfill: migrate the single platform OIDC config into the provider
registry + identity link table (history/auth-detailed-design.md §6.5, §11).

Runs on the **app_admin (BYPASSRLS) engine** because both the source
(``users``) and target (``federated_identities``) are FORCE ROW LEVEL SECURITY
— a policy-bound provisioning role would silently migrate 0/partial rows, the
data-loss trap we've hit before. Idempotent and self-healing: re-running once
the operator-global provider exists and every ``oidc_sub`` is linked is a no-op,
so it lives in ``lifespan`` and reconciles on every boot (like
``backfill_guild_schemas``).

The migrated provider is deliberately **operator-global** (``guild_id IS NULL``)
— today's OIDC is platform-level and must stay that way. ``app_settings.oidc_*``
and ``users.oidc_sub`` are left intact as the fallback; they are dropped only in
Phase 4 after the new path is proven.

The client secret rides along into the app_admin-only ``auth_provider_secrets``
companion (migration 0133): both columns use the same Fernet salt
(``SALT_OIDC_CLIENT_SECRET``), so the ciphertext moves **verbatim** — no
decrypt/re-encrypt. Like the provider row it is **create-once** (``ON CONFLICT
DO NOTHING``); a later secret rotation in ``app_settings`` is reconciled at
cutover, not re-copied every boot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlmodel import select

from app.db import session as db_session
from app.models.platform.app_setting import AppSetting
from app.models.platform.auth_provider import AuthProvider, AuthProviderKind

logger = logging.getLogger(__name__)

# Fixed slug for the one migrated platform provider: stable so re-runs find the
# existing row (idempotent) and so the legacy ``/auth/oidc/*`` alias keeps
# resolving once endpoints are generalized.
PLATFORM_OIDC_SLUG = "oidc"


@dataclass
class OidcBackfillSummary:
    """One-line boot log for the OIDC identity backfill."""

    provider_created: bool = False
    identities_linked: int = 0
    oidc_users: int = 0
    secret_migrated: bool = False
    skipped_reason: str | None = None


async def backfill_oidc_identity() -> OidcBackfillSummary:
    """Migrate ``app_settings.oidc_*`` → one operator-global ``auth_providers``
    row and link every ``users.oidc_sub`` into ``federated_identities``.

    Never raises: a failure is logged and returned as a skipped summary so a
    transient DB error can't take down boot (OIDC users keep the fallback path).
    """
    try:
        async with db_session.AdminSessionLocal() as session:
            return await _run(session)
    except Exception:
        logger.exception("OIDC identity back-fill failed; leaving legacy path intact")
        return OidcBackfillSummary(skipped_reason="error")


async def _run(session) -> OidcBackfillSummary:
    settings_row = (await session.exec(select(AppSetting))).first()
    # Fresh install or OIDC never configured → nothing to migrate.
    if (
        settings_row is None
        or not settings_row.oidc_issuer
        or not settings_row.oidc_client_id
    ):
        return OidcBackfillSummary(skipped_reason="oidc_not_configured")

    # 1. The one operator-global (guild_id IS NULL) provider row.
    provider = (
        await session.exec(
            select(AuthProvider).where(
                AuthProvider.slug == PLATFORM_OIDC_SLUG,
                AuthProvider.guild_id.is_(None),
            )
        )
    ).first()
    provider_created = provider is None
    if provider is None:
        scopes = settings_row.oidc_scopes or []
        provider = AuthProvider(
            slug=PLATFORM_OIDC_SLUG,
            display_name=settings_row.oidc_provider_name or "SSO",
            kind=AuthProviderKind.oidc.value,
            enabled=bool(settings_row.oidc_enabled),
            guild_id=None,  # operator-global: platform-level login
            issuer=settings_row.oidc_issuer,
            client_id=settings_row.oidc_client_id,
            scopes=" ".join(scopes) if scopes else None,
            role_claim_path=settings_row.oidc_role_claim_path,
            allow_jit=True,  # today's flow JIT-provisions unknown OIDC users
        )
        session.add(provider)
        await session.flush()

    # 2. Link every existing oidc_sub to that provider. Bulk INSERT … SELECT with
    #    ON CONFLICT so re-runs don't duplicate and a partly-migrated state heals.
    oidc_users = (
        await session.exec(
            text("SELECT count(*) FROM users WHERE oidc_sub IS NOT NULL")
        )
    ).scalar_one()

    result = await session.exec(
        text(
            "INSERT INTO federated_identities "
            "(user_id, provider_id, subject, email_verified, created_at) "
            "SELECT id, :pid, oidc_sub, true, now() FROM users "
            "WHERE oidc_sub IS NOT NULL "
            "ON CONFLICT (provider_id, subject) DO NOTHING"
        ),
        params={"pid": provider.id},
    )
    inserted = result.rowcount

    # 3. Migrate the client secret verbatim into the app_admin-only companion
    #    (auth_provider_secrets, migration 0133). Same Fernet salt on both
    #    columns, so the ciphertext moves as-is. Guarded on a secret actually
    #    being set — a public / PKCE-only provider gets no secret row. Create-once
    #    (ON CONFLICT DO NOTHING): idempotent, self-healing, and concurrency-safe;
    #    a rotated secret is reconciled at cutover, not re-copied here.
    secret_migrated = False
    if settings_row.oidc_client_secret_encrypted:
        secret_result = await session.exec(
            text(
                "INSERT INTO auth_provider_secrets "
                "(provider_id, client_secret_encrypted, created_at, updated_at) "
                "VALUES (:pid, :ct, now(), now()) "
                "ON CONFLICT (provider_id) DO NOTHING"
            ),
            params={
                "pid": provider.id,
                "ct": settings_row.oidc_client_secret_encrypted,
            },
        )
        secret_migrated = bool(secret_result.rowcount)

    await session.commit()

    # Row-count sanity: every oidc user should now be linked (freshly inserted or
    # already present). A shortfall means duplicate subjects collided — surface it.
    linked_total = (
        await session.exec(
            text("SELECT count(*) FROM federated_identities WHERE provider_id = :pid"),
            params={"pid": provider.id},
        )
    ).scalar_one()
    if linked_total < oidc_users:
        logger.warning(
            "OIDC identity back-fill: %d oidc users but only %d linked to "
            "provider %d — investigate duplicate subjects",
            oidc_users,
            linked_total,
            provider.id,
        )

    return OidcBackfillSummary(
        provider_created=provider_created,
        identities_linked=inserted,
        oidc_users=oidc_users,
        secret_migrated=secret_migrated,
    )
