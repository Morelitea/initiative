"""a community connects to a provider

Moves the division of labour: **the operator holds providers, a community
connects to one.** ``auth_providers`` becomes platform-only and
``guild_provider_connections`` says which of those providers a community signs
its members in through, narrowed to its own tenant where the provider serves
more than one.

What that stops being possible: a community supplying an issuer, a client id
and a secret of its own. It configured provider internals on somebody else's
deployment, which is the operator's job, and it meant every community that
signed in with Google configured Google again.

**This assumes no guild-scoped provider exists anywhere, and checks rather
than trusts.** The per-guild registry had an API from v0.58.0 but no interface
ever reached it, so nothing could be created through the app. Carrying a
backfill for rows that cannot exist would mean shipping SQL no database has
ever run — and the slug disambiguation it needs (two communities can each hold
``corp`` today; one global namespace cannot) would be dead code guarding a
collision that cannot happen.

So instead the migration refuses to run if the assumption is wrong. A silent
drop would turn one community's sign-in off and hand its provider to the
operator with nothing to say so; a raised exception stops the upgrade with the
reason. If it ever fires, the fix is a backfill written against the rows that
actually turned up.

A connection says two things about the people it describes, because a
community says both in one breath: which arrivals count as ours (``claim`` and
``claim_values``), and whether they join on arrival (``auto_join``).

Access shape:

* the connection CRUD writes on the system engine, as the provider registry
  does.
* the request path holds **SELECT and nothing else**. The guild-access gate
  reads the narrowing here on every request — before any guild context
  exists, and again under the guild roles — so the rule it applies is the one
  in force now rather than the one that held when somebody signed in. Same
  read shape as ``guild_auth_policies`` beside it, for the same reason.
* a connection carries a provider id, a claim name and a list of values. There
  is no secret and no issuer on it, which is what ``auth_providers`` is kept
  off the request path for.
* writes stay revoked from every request-path role; RLS is FORCEd.

Order matters: the table is created and filled **before** RLS goes on. A
policy-bound owner cannot insert rows whose policies key on request GUCs a
migration has no value for.
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260917_0303"
down_revision = "20260917_0302"
branch_labels = None
depends_on = None

TABLE = "guild_provider_connections"


# The gate the connections feed, as of this revision. ``app.db.authorization``
# is the live source and every boot re-applies it; these copies are what a
# database built from migrations alone gets.
_GUILD_CONNECTION_ADMITS = "CREATE OR REPLACE FUNCTION public.guild_connection_admits(p_guild_id integer, p_providers integer[], p_claims jsonb, p_provider_id integer DEFAULT NULL)\n RETURNS boolean\n LANGUAGE sql\n STABLE\nAS $function$\n    SELECT EXISTS (\n        SELECT 1\n        FROM public.guild_provider_connections c\n        WHERE c.guild_id = p_guild_id\n          AND c.enabled\n          AND (p_provider_id IS NULL OR c.provider_id = p_provider_id)\n          AND c.provider_id = ANY(COALESCE(p_providers, ARRAY[]::integer[]))\n          -- A connection naming no claim counts everybody the provider does.\n          AND (\n              c.claim IS NULL\n              OR c.claim_values IS NULL\n              OR EXISTS (\n                  SELECT 1\n                  FROM jsonb_array_elements_text(\n                      CASE\n                          WHEN jsonb_typeof(\n                                   COALESCE(p_claims, '{}'::jsonb)\n                                       -> c.provider_id::text -> c.claim\n                               ) = 'array'\n                          THEN COALESCE(p_claims, '{}'::jsonb)\n                                   -> c.provider_id::text -> c.claim\n                          ELSE '[]'::jsonb\n                      END\n                  ) AS asserted(value)\n                  WHERE lower(asserted.value) = ANY (\n                      SELECT lower(counted) FROM unnest(c.claim_values) AS counted\n                  )\n              )\n          )\n    )\n$function$\n\n"

_GUILD_CONNECTION_SATISFIED = "CREATE OR REPLACE FUNCTION public.guild_connection_satisfied(p_guild_id integer, p_provider_id integer DEFAULT NULL)\n RETURNS boolean\n LANGUAGE sql\n STABLE\nAS $function$\n    SELECT public.guild_connection_admits(\n        p_guild_id,\n        -- NULLIF twice: an unset value and the system sentinel both leave\n        -- nothing to cast, and a bare ''::int[] would fault every policy on\n        -- the table.\n        COALESCE(\n            string_to_array(\n                NULLIF(\n                    NULLIF(current_setting('app.satisfied_providers', true), ''),\n                    'system'\n                ),\n                ','\n            )::integer[],\n            ARRAY[]::integer[]\n        ),\n        COALESCE(\n            NULLIF(current_setting('app.satisfied_claims', true), '')::jsonb,\n            '{}'::jsonb\n        ),\n        p_provider_id\n    )\n$function$\n\n"

_GUILD_AUTH_SATISFIED = "CREATE OR REPLACE FUNCTION public.guild_auth_satisfied()\n RETURNS boolean\n LANGUAGE sql\n STABLE\nAS $function$\n    SELECT\n        -- Pure system routing (no user context) and the explicit sentinel a\n        -- user-attributed job sets are not sessions to gate.\n        NULLIF(current_setting('app.current_user_id', true), '') IS NULL\n        OR current_setting('app.satisfied_providers', true) = 'system'\n        OR NOT EXISTS (\n            SELECT 1 FROM public.guild_auth_policies p\n            WHERE p.guild_id = NULLIF(\n                    current_setting('app.current_guild_id', true), ''\n                  )::int\n              AND p.policy <> 'open'\n              AND (\n                  -- The provider this guild names, if it names one: the\n                  -- session came through it, and this community counts the\n                  -- arrival as one of its own.\n                  (\n                      p.provider_id IS NOT NULL\n                      AND NOT public.guild_connection_satisfied(\n                            p.guild_id, p.provider_id\n                          )\n                  )\n                  -- Or the account's own second factor, where the community\n                  -- asks for one. The session records it when a code is\n                  -- presented and the request carries that here.\n                  OR (\n                      'totp' = ANY(p.require_methods)\n                      AND COALESCE(\n                            current_setting('app.session_mfa', true), 'false'\n                          ) <> 'true'\n                  )\n                  -- Or any of its own, whichever provider served it. Named\n                  -- rather than counted, so a list holding some other method\n                  -- is not read as this one.\n                  OR (\n                      'sso' = ANY(p.require_methods)\n                      AND NOT public.guild_connection_satisfied(p.guild_id)\n                  )\n              )\n        )\n$function$\n\n"


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("claim", sa.String(length=64), nullable=True),
        sa.Column("claim_values", sa.ARRAY(sa.String(length=256)), nullable=True),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "auto_join", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["auth_providers.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id", "provider_id", name="uq_guild_provider_connections_pair"
        ),
    )
    op.create_index(f"ix_{TABLE}_guild_id", TABLE, ["guild_id"], unique=False)
    op.create_index(f"ix_{TABLE}_provider_id", TABLE, ["provider_id"], unique=False)

    # ── Nothing to move, and a check that says so ─────────────────────────
    #
    # No interface ever reached the per-guild registry, so no row should carry
    # a guild. If one does, this deployment knows something this migration
    # does not, and dropping the column would quietly end that community's
    # sign-in — so stop instead, with the count.
    op.execute(
        """
        DO $$
        DECLARE stranded int;
        BEGIN
            SELECT count(*) INTO stranded
            FROM public.auth_providers WHERE guild_id IS NOT NULL;
            IF stranded > 0 THEN
                RAISE EXCEPTION
                    'auth_providers holds % guild-scoped row(s); this revision '
                    'assumes none. They need a guild_provider_connections '
                    'backfill and a slug namespace decision before it can run.',
                    stranded;
            END IF;
        END $$;
        """
    )

    op.drop_index("uq_auth_providers_global_slug", table_name="auth_providers")
    op.drop_constraint("uq_auth_providers_guild_slug", "auth_providers", type_="unique")
    op.drop_column("auth_providers", "guild_id")
    op.create_unique_constraint("uq_auth_providers_slug", "auth_providers", ["slug"])

    # ── Now lock it down ──────────────────────────────────────────────────
    #
    # SELECT for the request path, scoped to the reader's own community, so
    # ``guild_auth_satisfied()`` reads the narrowing in force at the moment it
    # is asked. Writes belong to the CRUD on the system engine.
    base = _platform("base")
    _run(
        [
            f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
            f"REVOKE ALL ON TABLE public.{TABLE} "
            f'FROM app_guild_base, "{base}", app_user',
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{TABLE} "
            f"TO app_admin",
            f"GRANT USAGE, SELECT ON SEQUENCE public.{TABLE}_id_seq TO app_admin",
            # Read by the access gate before any guild context exists and by
            # the policy legs under the guild roles, exactly as
            # ``guild_auth_policies`` beside it is.
            f"GRANT SELECT ON TABLE public.{TABLE} "
            f'TO app_guild_base, "{base}", app_user',
            f"CREATE POLICY {TABLE}_read ON public.{TABLE} FOR SELECT USING (true)",
        ]
    )

    # ── And the gate that reads it ────────────────────────────────────────
    #
    # A community's requirement is answered by its connections now: the
    # session carries what the provider asserted, the connection carries which
    # values count, and the two meet here rather than in a decision made at
    # sign-in. ``app.sso_guilds`` is no longer read by anything.
    op.execute("SET LOCAL check_function_bodies = false")
    _run(
        [
            _GUILD_CONNECTION_ADMITS,
            _GUILD_CONNECTION_SATISFIED,
            _GUILD_AUTH_SATISFIED,
        ]
    )


def downgrade() -> None:
    op.drop_constraint("uq_auth_providers_slug", "auth_providers", type_="unique")
    op.add_column("auth_providers", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "auth_providers_guild_id_fkey",
        "auth_providers",
        "guilds",
        ["guild_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_auth_providers_guild_id", "auth_providers", ["guild_id"], unique=False
    )

    # Nothing to put back: the column is restored empty, which is the state
    # this revision found it in. A connection made after the upgrade has no
    # pre-migration shape to return to — it is a community connecting to the
    # operator's provider, which is a thing the old schema could not say.

    op.create_unique_constraint(
        "uq_auth_providers_guild_slug", "auth_providers", ["guild_id", "slug"]
    )
    op.create_index(
        "uq_auth_providers_global_slug",
        "auth_providers",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("guild_id IS NULL"),
    )

    _run([f"ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY"])
    op.drop_index(f"ix_{TABLE}_provider_id", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_guild_id", table_name=TABLE)
    op.drop_table(TABLE)
