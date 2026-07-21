"""Drop ``app_settings.oidc_*`` — the provider registry row is the config.

Final-cutover step for the platform OIDC config columns. The operator-global
``auth_providers`` row (slug ``oidc``) is now written directly by the settings
endpoints and read by the login path and refresh sweep; the reconcile-from-
settings shim is gone.

Before dropping, this migration folds the columns' last state into the
registry row so nothing the operator configured is lost — including drift
written after migration 0151 seeded the row (the old settings endpoint kept
writing the columns until this release):

1. Create the platform row from ``app_settings`` if OIDC was configured and
   no row exists (same mapping as 0151).
2. Update an existing row's fields from the columns (the columns were
   authoritative until now).
3. Mirror the client-secret ciphertext (verbatim — shared Fernet salt):
   set when the column holds one, cleared when it doesn't.

The tables are FORCE ROW LEVEL SECURITY (policy-bound even for the owner this
migration runs as — reads would silently return zero rows); the flag is
lifted for the copy and restored inside the same transaction. Every statement
is a no-op on a fresh database.

Downgrade restores the column shapes only (defaults matching the original
DDL); the data move is one-way — the registry row stays authoritative.

Revision ID: 20260720_0153
Revises: 20260720_0152
Create Date: 2026-07-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260720_0153"
down_revision = "20260720_0152"
branch_labels = None
depends_on = None

_FORCE_RLS_TABLES = (
    "app_settings",
    "auth_providers",
    "auth_provider_secrets",
)


def upgrade() -> None:
    for table in _FORCE_RLS_TABLES:
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")

    # 1. Create the platform row when OIDC was configured but no row exists
    #    (an install that skipped every boot since 0151 — the same mapping).
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

    # 2. Fold the columns' final state into an existing row — they were the
    #    operator's authoritative surface until this release, so the columns
    #    win over whatever the row currently carries. Only when configured;
    #    an unconfigured install keeps its (dormant) row untouched apart from
    #    the claim path, which the mappings UI could set independently.
    op.execute(
        """
        UPDATE auth_providers p
        SET display_name = COALESCE(s.oidc_provider_name, 'SSO'),
            enabled = s.oidc_enabled,
            issuer = s.oidc_issuer,
            client_id = s.oidc_client_id,
            scopes = NULLIF(array_to_string(
                ARRAY(SELECT json_array_elements_text(s.oidc_scopes)), ' '), ''),
            role_claim_path = s.oidc_role_claim_path,
            updated_at = now()
        FROM (SELECT * FROM app_settings ORDER BY id LIMIT 1) s
        WHERE p.slug = 'oidc' AND p.guild_id IS NULL
          AND s.oidc_issuer IS NOT NULL AND s.oidc_client_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE auth_providers p
        SET role_claim_path = s.oidc_role_claim_path,
            updated_at = now()
        FROM (SELECT * FROM app_settings ORDER BY id LIMIT 1) s
        WHERE p.slug = 'oidc' AND p.guild_id IS NULL
          AND (s.oidc_issuer IS NULL OR s.oidc_client_id IS NULL)
          AND s.oidc_role_claim_path IS NOT NULL
          AND p.role_claim_path IS DISTINCT FROM s.oidc_role_claim_path
        """
    )

    # 3. Client secret, ciphertext verbatim (shared Fernet salt). The column
    #    was authoritative: a stored value replaces the companion's, an empty
    #    column clears it (public / PKCE-only client).
    op.execute(
        """
        INSERT INTO auth_provider_secrets
            (provider_id, client_secret_encrypted, created_at, updated_at)
        SELECT p.id, s.oidc_client_secret_encrypted, now(), now()
        FROM auth_providers p,
             (SELECT * FROM app_settings ORDER BY id LIMIT 1) s
        WHERE p.slug = 'oidc' AND p.guild_id IS NULL
          AND s.oidc_client_secret_encrypted IS NOT NULL
        ON CONFLICT (provider_id) DO UPDATE
            SET client_secret_encrypted = EXCLUDED.client_secret_encrypted,
                updated_at = now()
        """
    )
    op.execute(
        """
        UPDATE auth_provider_secrets sec
        SET client_secret_encrypted = NULL,
            updated_at = now()
        FROM auth_providers p,
             (SELECT * FROM app_settings ORDER BY id LIMIT 1) s
        WHERE sec.provider_id = p.id
          AND p.slug = 'oidc' AND p.guild_id IS NULL
          AND s.oidc_client_secret_encrypted IS NULL
          AND sec.client_secret_encrypted IS NOT NULL
        """
    )

    for table in _FORCE_RLS_TABLES:
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")

    op.drop_column("app_settings", "oidc_enabled")
    op.drop_column("app_settings", "oidc_issuer")
    op.drop_column("app_settings", "oidc_client_id")
    op.drop_column("app_settings", "oidc_client_secret_encrypted")
    op.drop_column("app_settings", "oidc_provider_name")
    op.drop_column("app_settings", "oidc_scopes")
    op.drop_column("app_settings", "oidc_role_claim_path")


def downgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "oidc_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("app_settings", sa.Column("oidc_issuer", sa.String(), nullable=True))
    op.add_column(
        "app_settings", sa.Column("oidc_client_id", sa.String(), nullable=True)
    )
    op.add_column(
        "app_settings",
        sa.Column("oidc_client_secret_encrypted", sa.String(), nullable=True),
    )
    op.add_column(
        "app_settings", sa.Column("oidc_provider_name", sa.String(), nullable=True)
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "oidc_scopes",
            sa.JSON(),
            nullable=False,
            server_default='["openid","profile","email","offline_access"]',
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column("oidc_role_claim_path", sa.String(length=500), nullable=True),
    )
