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
* the request path holds **SELECT and nothing else**, scoped by policy to the
  reader's own community. The guild-access gate reads the narrowing here on
  every request, so the rule it applies is the one in force now rather than
  the one that held when somebody signed in.
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

revision = "20260917_0300"
down_revision = "20260917_0299"
branch_labels = None
depends_on = None

TABLE = "guild_provider_connections"


_OWN_GUILD = "guild_id = NULLIF(current_setting('app.current_guild_id', true), '')::int"


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
            f"GRANT SELECT ON TABLE public.{TABLE} TO app_guild_base",
            f"CREATE POLICY {TABLE}_own_guild ON public.{TABLE} "
            f"FOR SELECT TO public USING ({_OWN_GUILD})",
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
