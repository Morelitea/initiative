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

Provider creation + secret migration are delegated to
:mod:`app.services.auth.platform_provider` — the same reconcile the login path
runs — so there is exactly one code path that maps ``app_settings.oidc_*`` onto
the provider row. Since the login cutover that reconcile also folds in drift
(a settings edit or secret rotation), on boot and on every login alike.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlmodel import select

from app.db import session as db_session
from app.models.platform.app_setting import AppSetting
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.services.auth.platform_provider import (
    PLATFORM_OIDC_SLUG as PLATFORM_OIDC_SLUG,  # re-export (public name)
    ensure_platform_provider,
    get_platform_provider,
)

logger = logging.getLogger(__name__)


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

    # 1. The one operator-global (guild_id IS NULL) provider row — created or
    #    drift-reconciled by the shared settings→provider mapping (the same one
    #    the login path runs). Before/after reads only feed the boot summary.
    existing = await get_platform_provider(session)
    provider_created = existing is None
    secret_before = None
    if existing is not None:
        secret_row = await session.get(AuthProviderSecret, existing.id)
        if secret_row is not None:
            secret_before = secret_row.client_secret_encrypted
    provider = await ensure_platform_provider(session, settings_row)

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

    # 3. The client secret was reconciled into auth_provider_secrets by
    #    ensure_platform_provider above (ciphertext verbatim — same Fernet salt
    #    on both columns); here we only compute the summary flag.
    secret_migrated = bool(
        settings_row.oidc_client_secret_encrypted
        and settings_row.oidc_client_secret_encrypted != secret_before
    )

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
