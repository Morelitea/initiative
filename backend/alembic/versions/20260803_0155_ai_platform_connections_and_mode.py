"""add platform_ai_connections + AI config mode; drop legacy ai_* columns

Public half of the AI refactor (the guild-schema half is 20260803_0154):

* ``platform_ai_connections`` — the operator's AI connections for ``platform``
  mode. Owner-managed + system-engine-read only (the request path reads it via
  an in-process cache on the system engine, never under a guild role), so the
  base/login roles get nothing and only ``platform_owner`` + ``app_admin`` are
  granted. RLS-forced with a single owner policy (mirrors ``app_settings`` minus
  the broad read — this table holds key ciphertext).
* ``app_settings.ai_config_mode`` + ``ai_allow_member_keys`` replace the old
  cascade toggles.
* A configured+enabled platform provider on ``app_settings`` is preserved into a
  ``platform_ai_connections`` row (keeping the encrypted key) and the mode set to
  ``platform``; then the legacy ``app_settings.ai_*`` and ``users.ai_*`` columns
  are dropped. A user-level key has no connection to attach to under the new
  model, so ``users.ai_*`` is dropped without migration.
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260803_0155"
down_revision = "20260803_0154"
branch_labels = None
depends_on = None


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    # 1. New operator-connection table (RLS enabled AFTER the data copy below, so
    #    the provisioner's INSERT isn't policy-bound on a fresh table).
    op.create_table(
        "platform_ai_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("base_url", sa.String(length=1000), nullable=True),
        sa.Column("model", sa.String(length=500), nullable=True),
        sa.Column("api_key_encrypted", sa.String(length=2000), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. New app_settings mode columns (existing row gets the server defaults).
    op.add_column(
        "app_settings",
        sa.Column(
            "ai_config_mode",
            sa.String(length=20),
            server_default="disabled",
            nullable=False,
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "ai_allow_member_keys",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
    )

    # 3. Preserve a configured+enabled platform provider into a connection row,
    #    and switch the mode to platform. Runs before RLS is enabled on the new
    #    table, so the provisioner is unrestricted here.
    op.execute(
        sa.text(
            """
            INSERT INTO public.platform_ai_connections
                (label, provider, base_url, model, api_key_encrypted,
                 enabled, is_default, created_at, updated_at)
            SELECT 'Imported connection', ai_provider, ai_base_url, ai_model,
                   ai_api_key_encrypted, COALESCE(ai_enabled, true), true,
                   now(), now()
            FROM public.app_settings
            WHERE id = 1 AND ai_provider IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE public.app_settings SET ai_config_mode = 'platform'
            WHERE id = 1 AND ai_provider IS NOT NULL
              AND COALESCE(ai_enabled, false) = true
            """
        )
    )

    # 4. Lock down platform_ai_connections: owner + system engine only. The
    #    schema default-grants base/login roles full DML on every new public
    #    table, so REVOKE them (the request path never touches this table — it is
    #    read via the system-engine cache), then GRANT exactly the two roles that
    #    use it. RLS-forced with a single owner policy (platform_owner is not
    #    BYPASSRLS, so it needs the policy; app_admin bypasses RLS).
    base = _platform("base")
    owner = _platform("owner")
    _run(
        [
            "ALTER TABLE public.platform_ai_connections ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.platform_ai_connections FORCE ROW LEVEL SECURITY",
            "REVOKE ALL ON TABLE public.platform_ai_connections "
            f'FROM app_guild_base, "{base}", app_user',
            # SELECT for the request-path cache loader; UPDATE for the
            # secret-key rotation re-encrypting the key column.
            "GRANT SELECT, UPDATE ON TABLE public.platform_ai_connections TO app_admin",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
            f'public.platform_ai_connections TO "{owner}"',
            "DROP POLICY IF EXISTS platform_ai_connections_owner "
            "ON public.platform_ai_connections",
            "CREATE POLICY platform_ai_connections_owner "
            "ON public.platform_ai_connections AS PERMISSIVE FOR ALL "
            f'TO "{owner}" USING (true) WITH CHECK (true)',
        ]
    )

    # 5. Drop the legacy cascade columns.
    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.drop_column("ai_enabled")
        batch_op.drop_column("ai_provider")
        batch_op.drop_column("ai_api_key_encrypted")
        batch_op.drop_column("ai_base_url")
        batch_op.drop_column("ai_model")
        batch_op.drop_column("ai_allow_guild_override")
        batch_op.drop_column("ai_allow_user_override")

    # 6. Standalone user AI is removed; a user key has no connection to attach to.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("ai_enabled")
        batch_op.drop_column("ai_provider")
        batch_op.drop_column("ai_api_key_encrypted")
        batch_op.drop_column("ai_base_url")
        batch_op.drop_column("ai_model")


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ai_enabled", sa.Boolean(), nullable=True))
        batch_op.add_column(
            sa.Column("ai_provider", sa.String(length=50), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ai_api_key_encrypted", sa.String(length=2000), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ai_base_url", sa.String(length=1000), nullable=True)
        )
        batch_op.add_column(sa.Column("ai_model", sa.String(length=500), nullable=True))

    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "ai_enabled",
                sa.Boolean(),
                server_default="false",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("ai_provider", sa.String(length=50), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ai_api_key_encrypted", sa.String(length=2000), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ai_base_url", sa.String(length=1000), nullable=True)
        )
        batch_op.add_column(sa.Column("ai_model", sa.String(length=500), nullable=True))
        batch_op.add_column(
            sa.Column(
                "ai_allow_guild_override",
                sa.Boolean(),
                server_default="true",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "ai_allow_user_override",
                sa.Boolean(),
                server_default="true",
                nullable=False,
            )
        )
        batch_op.drop_column("ai_allow_member_keys")
        batch_op.drop_column("ai_config_mode")

    op.execute("DROP TABLE IF EXISTS public.platform_ai_connections CASCADE")
