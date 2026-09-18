"""a deployment answers once for the communities that have not

Some deployments are one organisation: one identity provider, one tenant, and
communities that are its teams. Two hundred teams repeating the same
arrangement makes the operator their queue, which is the thing this design is
built to avoid. So ``platform_provider_defaults`` lets an operator answer once
for a provider, and a community inherits that answer until it gives its own.

**The unit of override is the connection.** A community's own row in
``guild_provider_connections`` shadows the default outright — one row shadowing
one row, nothing to merge — and that includes a row written with ``enabled``
off, which is how a community declines a default. Which provider is ours and
who on it counts as ours is an arrangement, and on an arrangement the community
wins; the floors it may only tighten are elsewhere and unchanged.

A default carries no ``auto_join``. It names a provider, never a community, so
joining on it would place an arrival in every community that had not spoken —
and who joins a community is the community's own decision. One that wants
arrivals joined writes its own connection, seeded from this.

Its own table rather than columns on ``auth_providers``, because the gate reads
this on the request path and the registry is not readable there. A default
holds none of the registry's configuration: a provider id, a claim name, a list
of values.

Access shape: identical to the connections it stands in for — written on the
system engine, read by the request path and nothing more.

Nothing to backfill: a fresh table, and no deployment has expressed a default
before now, so every community keeps exactly the arrangement it has.

Revision ID: 20260917_0305
Revises: 20260917_0304
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260917_0305"
down_revision = "20260917_0304"
branch_labels = None
depends_on = None

TABLE = "platform_provider_defaults"


# The gate, as of this revision. ``app.db.authorization`` is the live source
# and every boot re-applies it; this copy is what a database built from
# migrations alone gets.
_GUILD_CONNECTION_ADMITS = "CREATE OR REPLACE FUNCTION public.guild_connection_admits(p_guild_id integer, p_providers integer[], p_claims jsonb, p_provider_id integer DEFAULT NULL::integer)\n RETURNS boolean\n LANGUAGE sql\n STABLE\nAS $function$\n    WITH effective AS (\n        -- What this community said, and the deployment's own answer for a\n        -- provider it has said nothing about. One row shadows one row: a\n        -- community's own connection replaces the default outright, including\n        -- one it wrote with `enabled` off to decline it.\n        SELECT c.provider_id, c.enabled, c.claim, c.claim_values\n        FROM public.guild_provider_connections c\n        WHERE c.guild_id = p_guild_id\n        UNION ALL\n        SELECT d.provider_id, d.enabled, d.claim, d.claim_values\n        FROM public.platform_provider_defaults d\n        WHERE NOT EXISTS (\n            SELECT 1\n            FROM public.guild_provider_connections own\n            WHERE own.guild_id = p_guild_id\n              AND own.provider_id = d.provider_id\n        )\n    )\n    SELECT EXISTS (\n        SELECT 1\n        FROM effective c\n        WHERE c.enabled\n          AND (p_provider_id IS NULL OR c.provider_id = p_provider_id)\n          AND c.provider_id = ANY(COALESCE(p_providers, ARRAY[]::integer[]))\n          -- A connection naming no claim counts everybody the provider does.\n          AND (\n              c.claim IS NULL\n              OR c.claim_values IS NULL\n              OR EXISTS (\n                  SELECT 1\n                  FROM jsonb_array_elements_text(\n                      CASE\n                          WHEN jsonb_typeof(\n                                   COALESCE(p_claims, '{}'::jsonb)\n                                       -> c.provider_id::text -> c.claim\n                               ) = 'array'\n                          THEN COALESCE(p_claims, '{}'::jsonb)\n                                   -> c.provider_id::text -> c.claim\n                          ELSE '[]'::jsonb\n                      END\n                  ) AS asserted(value)\n                  WHERE lower(asserted.value) = ANY (\n                      SELECT lower(counted) FROM unnest(c.claim_values) AS counted\n                  )\n              )\n          )\n    )\n$function$\n\n"

# The same function before defaults existed, for the downgrade.
_GUILD_CONNECTION_ADMITS_PREVIOUS = "CREATE OR REPLACE FUNCTION public.guild_connection_admits(p_guild_id integer, p_providers integer[], p_claims jsonb, p_provider_id integer DEFAULT NULL::integer)\n RETURNS boolean\n LANGUAGE sql\n STABLE\nAS $function$\n    SELECT EXISTS (\n        SELECT 1\n        FROM public.guild_provider_connections c\n        WHERE c.guild_id = p_guild_id\n          AND c.enabled\n          AND (p_provider_id IS NULL OR c.provider_id = p_provider_id)\n          AND c.provider_id = ANY(COALESCE(p_providers, ARRAY[]::integer[]))\n          -- A connection naming no claim counts everybody the provider does.\n          AND (\n              c.claim IS NULL\n              OR c.claim_values IS NULL\n              OR EXISTS (\n                  SELECT 1\n                  FROM jsonb_array_elements_text(\n                      CASE\n                          WHEN jsonb_typeof(\n                                   COALESCE(p_claims, '{}'::jsonb)\n                                       -> c.provider_id::text -> c.claim\n                               ) = 'array'\n                          THEN COALESCE(p_claims, '{}'::jsonb)\n                                   -> c.provider_id::text -> c.claim\n                          ELSE '[]'::jsonb\n                      END\n                  ) AS asserted(value)\n                  WHERE lower(asserted.value) = ANY (\n                      SELECT lower(counted) FROM unnest(c.claim_values) AS counted\n                  )\n              )\n          )\n    )\n$function$\n\n"


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("claim", sa.String(length=64), nullable=True),
        sa.Column("claim_values", sa.ARRAY(sa.String(length=256)), nullable=True),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["auth_providers.id"], ondelete="CASCADE"
        ),
        # One answer per provider, so the provider is the key.
        sa.PrimaryKeyConstraint("provider_id"),
    )

    # ── Lock it down ──────────────────────────────────────────────────────
    #
    # The connections' own shape: writes on the system engine, SELECT for the
    # request path so the gate reads the arrangement in force at the moment it
    # is asked rather than one worked out at sign-in.
    base = _platform("base")
    _run(
        [
            f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
            f"REVOKE ALL ON TABLE public.{TABLE} "
            f'FROM app_guild_base, "{base}", app_user',
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{TABLE} "
            f"TO app_admin",
            f"GRANT SELECT ON TABLE public.{TABLE} "
            f'TO app_guild_base, "{base}", app_user',
            f"CREATE POLICY {TABLE}_read ON public.{TABLE} FOR SELECT USING (true)",
        ]
    )

    # ── And the gate that now reads both ──────────────────────────────────
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(_GUILD_CONNECTION_ADMITS)


def downgrade() -> None:
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(_GUILD_CONNECTION_ADMITS_PREVIOUS)
    _run(
        [
            f"DROP POLICY IF EXISTS {TABLE}_read ON public.{TABLE}",
            f"ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY",
        ]
    )
    op.drop_table(TABLE)
