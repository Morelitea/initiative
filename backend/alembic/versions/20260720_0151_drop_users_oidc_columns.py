"""Drop ``users.oidc_*`` — identity now lives on ``federated_identities``.

Final-cutover step for the per-user legacy OIDC columns (``oidc_sub``,
``oidc_refresh_token_encrypted``, ``oidc_last_synced_at``). Their successors
(``federated_identities`` + ``federated_identity_secrets``) have carried the
login path since the session-model release; the boot backfill
(``app.services.auth.oidc_backfill``) kept the two in sync and is retired in
the same release as this migration.

Before dropping, this migration re-runs the backfill's copy **idempotently in
SQL** — an install can upgrade straight from a version that never booted the
backfill, so the drop must not depend on boot-time code having run:

1. Ensure the operator-global provider row exists (from ``app_settings``,
   ciphertext secret copied verbatim — both columns share a Fernet salt).
2. Link every ``users.oidc_sub`` into ``federated_identities``.
3. Copy per-user refresh tokens + sync stamps onto the links (gaps only —
   values the new login path already wrote are never overwritten).

The copy tables are all FORCE ROW LEVEL SECURITY, which binds even the owner
(the provisioning role migrations run as) — reads would silently return zero
rows. The FORCE flag is lifted for the copy and restored right after, inside
the same transaction. Every statement is a no-op on a fresh database.

Downgrade restores the column shapes only; the data move is one-way (the
successors remain authoritative).

Revision ID: 20260720_0151
Revises: 20260720_0150
Create Date: 2026-07-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260720_0151"
down_revision = "20260720_0150"
branch_labels = None
depends_on = None

# Tables the copy below reads or writes. All six carry FORCE ROW LEVEL
# SECURITY at this point in history (baseline for users/app_settings;
# migrations 0131/0133/0142 for the auth tables), so the list is static.
_FORCE_RLS_TABLES = (
    "users",
    "app_settings",
    "auth_providers",
    "auth_provider_secrets",
    "federated_identities",
    "federated_identity_secrets",
)


def upgrade() -> None:
    for table in _FORCE_RLS_TABLES:
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")

    # 1. The operator-global provider row (slug 'oidc', guild_id IS NULL),
    #    created from app_settings when OIDC was configured but no boot ever
    #    reconciled it. Field mapping mirrors platform_provider._create_provider.
    op.execute(
        """
        INSERT INTO auth_providers
            (slug, display_name, kind, enabled, guild_id, issuer, client_id,
             scopes, role_claim_path, allow_jit, created_at, updated_at)
        SELECT 'oidc',
               COALESCE(s.oidc_provider_name, 'SSO'),
               'oidc',
               s.oidc_enabled,
               NULL,
               s.oidc_issuer,
               s.oidc_client_id,
               NULLIF(array_to_string(
                   ARRAY(SELECT json_array_elements_text(s.oidc_scopes)), ' '), ''),
               s.oidc_role_claim_path,
               true,
               now(),
               now()
        FROM (SELECT * FROM app_settings ORDER BY id LIMIT 1) s
        WHERE s.oidc_issuer IS NOT NULL AND s.oidc_client_id IS NOT NULL
        ON CONFLICT (slug) WHERE guild_id IS NULL DO NOTHING
        """
    )

    # 2. Client secret ciphertext, verbatim (same Fernet salt on both columns).
    #    Gaps only — a secret the provider CRUD already wrote is kept.
    op.execute(
        """
        INSERT INTO auth_provider_secrets
            (provider_id, client_secret_encrypted, created_at, updated_at)
        SELECT p.id,
               (SELECT oidc_client_secret_encrypted FROM app_settings
                ORDER BY id LIMIT 1),
               now(),
               now()
        FROM auth_providers p
        WHERE p.slug = 'oidc' AND p.guild_id IS NULL
          AND (SELECT oidc_client_secret_encrypted FROM app_settings
               ORDER BY id LIMIT 1) IS NOT NULL
        ON CONFLICT (provider_id) DO NOTHING
        """
    )

    # 3. Link every legacy oidc_sub to the platform provider.
    op.execute(
        """
        INSERT INTO federated_identities
            (user_id, provider_id, subject, email_verified, created_at)
        SELECT u.id, p.id, u.oidc_sub, true, now()
        FROM users u
        JOIN auth_providers p ON p.slug = 'oidc' AND p.guild_id IS NULL
        WHERE u.oidc_sub IS NOT NULL
        ON CONFLICT (provider_id, subject) DO NOTHING
        """
    )

    # 4. Per-user refresh tokens onto the links (verbatim ciphertext; gaps only).
    op.execute(
        """
        INSERT INTO federated_identity_secrets
            (identity_id, refresh_token_encrypted, created_at, updated_at)
        SELECT fi.id, u.oidc_refresh_token_encrypted, now(), now()
        FROM federated_identities fi
        JOIN users u ON u.id = fi.user_id AND u.oidc_sub = fi.subject
        JOIN auth_providers p
            ON p.id = fi.provider_id AND p.slug = 'oidc' AND p.guild_id IS NULL
        WHERE u.oidc_refresh_token_encrypted IS NOT NULL
        ON CONFLICT (identity_id) DO NOTHING
        """
    )

    # 5. Sync stamps (gaps only — never overwrite a fresher link value).
    op.execute(
        """
        UPDATE federated_identities fi
        SET last_synced_at = u.oidc_last_synced_at
        FROM users u, auth_providers p
        WHERE u.id = fi.user_id AND u.oidc_sub = fi.subject
          AND p.id = fi.provider_id AND p.slug = 'oidc' AND p.guild_id IS NULL
          AND fi.last_synced_at IS NULL
          AND u.oidc_last_synced_at IS NOT NULL
        """
    )

    for table in _FORCE_RLS_TABLES:
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")

    op.drop_column("users", "oidc_sub")
    op.drop_column("users", "oidc_refresh_token_encrypted")
    op.drop_column("users", "oidc_last_synced_at")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("oidc_sub", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("oidc_refresh_token_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("oidc_last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
