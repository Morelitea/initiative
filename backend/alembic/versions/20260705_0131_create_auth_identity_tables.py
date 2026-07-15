"""create auth provider registry + federated identity tables

Phase-0 foundation for the login rewrite (history/auth-detailed-design.md):
two secret-free ``public`` tables. Additive only — nothing reads or writes them
yet, so there is no behaviour change and no dual-verify window needed.

Role security follows the least-privilege posture, NOT a blanket copy of an
existing table:

* ``auth_providers`` — like ``oidc_claim_mappings``: RLS ENABLE+FORCE with NO
  permissive policy, granted only to ``app_admin``. The request path never reads
  provider config directly (login + CRUD run on the system engine).
* ``federated_identities`` — own-row ``_self`` policy; ``app_admin`` does the
  writes (login resolve/create, link/unlink); the platform request path gets
  SELECT for the "your sign-in methods" view. No guild-role grant (identity is
  account-level, never touched from a guild schema).
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260705_0131"
down_revision = "20260705_0130"
branch_labels = None
depends_on = None


def _platform(role: str) -> str:
    """Prefixed platform-tier role name (empty prefix in prod/dev)."""
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.create_table(
        "auth_providers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), server_default="oidc", nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("guild_id", sa.Integer(), nullable=True),
        sa.Column("issuer", sa.Text(), nullable=True),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("role_claim_path", sa.Text(), nullable=True),
        sa.Column("connection_claim", sa.String(length=64), nullable=True),
        sa.Column(
            "allow_jit", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("icon", sa.String(length=64), nullable=True),
        sa.Column("button_style", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("guild_id", "slug", name="uq_auth_providers_guild_slug"),
        sa.CheckConstraint(
            "kind IN ('oidc', 'oauth2', 'broker')", name="ck_auth_providers_kind"
        ),
    )
    op.create_index("ix_auth_providers_guild_id", "auth_providers", ["guild_id"])
    # Operator-global slugs (guild_id IS NULL — not covered by the composite
    # unique above, since NULLs compare distinct) must be unique too.
    op.create_index(
        "uq_auth_providers_global_slug",
        "auth_providers",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("guild_id IS NULL"),
    )

    op.create_table(
        "federated_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["auth_providers.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "provider_id", "subject", name="uq_federated_identities_provider_subject"
        ),
    )
    op.create_index(
        "ix_federated_identities_user_id", "federated_identities", ["user_id"]
    )
    op.create_index(
        "ix_federated_identities_provider_id", "federated_identities", ["provider_id"]
    )

    base = _platform("base")
    _self = "(user_id = (NULLIF(current_setting('app.current_user_id', true), ''))::integer)"

    # NOTE: the public schema has default privileges that GRANT platform_base +
    # app_guild_base full DML on EVERY new public table. So a new shared table is
    # request-path-writable unless we explicitly REVOKE — RLS alone would be the
    # only guard. We revoke to get grant-layer denial too (defense in depth).
    _run(
        [
            # --- auth_providers: system-engine (app_admin) only ---
            "ALTER TABLE public.auth_providers ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.auth_providers FORCE ROW LEVEL SECURITY",
            # Strip the schema-default DML: nothing on the request path reads
            # provider config (login + CRUD run on app_admin).
            f'REVOKE ALL ON TABLE public.auth_providers FROM app_guild_base, "{base}"',
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.auth_providers TO app_admin",
            "GRANT ALL ON SEQUENCE public.auth_providers_id_seq TO app_admin",
            # --- federated_identities: own-row reads; writes via the system engine ---
            "ALTER TABLE public.federated_identities ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.federated_identities FORCE ROW LEVEL SECURITY",
            (
                "CREATE POLICY federated_identities_self ON public.federated_identities "
                f"USING {_self} WITH CHECK {_self}"
            ),
            # Identity is account-level (never touched from a guild schema) and
            # link/unlink runs on the system engine only. Drop the default DML
            # to a clean slate, then re-grant only the platform request path
            # SELECT for the own-row "your sign-in methods" read.
            f'REVOKE ALL ON TABLE public.federated_identities FROM app_guild_base, "{base}"',
            f'GRANT SELECT ON TABLE public.federated_identities TO "{base}"',
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.federated_identities TO app_admin",
            "GRANT ALL ON SEQUENCE public.federated_identities_id_seq TO app_admin",
        ]
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.federated_identities CASCADE")
    op.execute("DROP TABLE IF EXISTS public.auth_providers CASCADE")
