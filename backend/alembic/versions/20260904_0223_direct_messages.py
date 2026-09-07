"""Who may ask to message whom.

Four tables in ``public``, all per-account and cross-guild:

* ``user_dm_settings`` — the policy an account picked, one row per account.
  Kept off ``public.users`` because that table is read whole by the platform
  tiers, and this is the account holder's own business.
* ``user_dm_guild_optouts`` — the communities it switched off, stored as the
  exceptions so a newly joined one counts with no write.
* ``contact_grants`` — the canonical pair, one row per ``kind``: a connection,
  and the accepted message request that opens a channel.
* ``user_ignores`` — the accounts it has chosen not to hear from.

Access shape, the same for all four: **the account holder's own rows, and
nothing else on the request path.** No platform-tier policy, no guild-admin
leg, no PAM leg. ``app_guild_base`` — what every ``guild_<id>`` role inherits —
is granted nothing at all, matching the shape 0221 put the guild path into.

Two functions answer questions the request path cannot ask directly, on the
``app_profile_reader`` pattern from 0214: a ``NOLOGIN`` role holding SELECT and
an all-rows policy on what the rule reads, owning ``SECURITY DEFINER``
functions that return a decision rather than a row. Neither takes a caller id —
they read ``app.current_user_id`` — so the caller is the current user by
construction.

``user_dm_settings`` is backfilled for every existing account, which decides
the order: the rows go in before ``FORCE ROW LEVEL SECURITY``, because the
policies key on request GUCs a migration has no value for.

Revision ID: 20260904_0223
Revises: 20260904_0222
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision = "20260904_0223"
down_revision = "20260904_0222"
branch_labels = None
depends_on = None

#: The reader role behind the two functions. Cluster-wide and unprefixed, like
#: ``app_profile_reader`` (0214) and the other base roles.
READER = "app_dm_reader"

_TABLES = (
    "user_dm_settings",
    "user_dm_guild_optouts",
    "contact_grants",
    "user_ignores",
)

# NULLIF-guarded: an unset context leaves the value empty, and a bare ''::int
# would raise and fault the whole query rather than fail the policy.
_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def _create_tables() -> None:
    op.create_table(
        "user_dm_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "dm_policy",
            sa.Enum("private", "community", "public", name="user_dm_policy"),
            nullable=False,
            server_default="private",
        ),
        sa.Column(
            "send_receipts",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "user_dm_guild_optouts",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "guild_id"),
    )
    op.create_table(
        "contact_grants",
        sa.Column("user_id_low", sa.Integer(), nullable=False),
        sa.Column("user_id_high", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("connection", "message", name="contact_grant_kind"),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.Enum("pending", "accepted", name="contact_grant_state"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id_low"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id_high"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id_low", "user_id_high", "kind"),
        sa.CheckConstraint(
            "user_id_low < user_id_high", name="ck_contact_grants_ordered_pair"
        ),
        sa.CheckConstraint(
            "requested_by IN (user_id_low, user_id_high)",
            name="ck_contact_grants_requester_in_pair",
        ),
    )
    op.create_index("ix_contact_grants_user_high", "contact_grants", ["user_id_high"])
    op.create_table(
        "user_ignores",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ignored_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ignored_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "ignored_user_id"),
        sa.CheckConstraint(
            "user_id <> ignored_user_id", name="ck_user_ignores_not_self"
        ),
    )
    op.create_index("ix_user_ignores_ignored_user", "user_ignores", ["ignored_user_id"])


#: The rule, in one place. ``dm_can_ask`` is the policy table; the two entry
#: points below compose it and add what their own callers need.
_FUNCTIONS = [
    """
    CREATE OR REPLACE FUNCTION public.dm_can_ask(from_id int, to_id int)
    RETURNS boolean
    LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $fn$
      SELECT CASE
        WHEN EXISTS (
          SELECT 1 FROM public.contact_grants g
          WHERE g.user_id_low = LEAST(from_id, to_id)
            AND g.user_id_high = GREATEST(from_id, to_id)
            AND g.kind = 'connection'
            AND g.state = 'accepted'
        ) THEN true
        ELSE COALESCE((
          SELECT CASE s.dm_policy
            WHEN 'public' THEN true
            WHEN 'community' THEN EXISTS (
              SELECT 1
              FROM public.guild_memberships a
              JOIN public.guild_memberships b ON b.guild_id = a.guild_id
              JOIN public.guilds gg ON gg.id = a.guild_id
              WHERE a.user_id = from_id
                AND b.user_id = to_id
                AND gg.status <> 'suspended'
                AND NOT EXISTS (
                  SELECT 1 FROM public.user_dm_guild_optouts o
                  WHERE o.user_id = to_id AND o.guild_id = a.guild_id
                )
            )
            ELSE false
          END
          FROM public.user_dm_settings s WHERE s.user_id = to_id
        ), false)
      END
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.dm_reachable(account_id int)
    RETURNS boolean
    LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $fn$
      SELECT EXISTS (
        SELECT 1 FROM public.users u
        WHERE u.id = account_id
          AND u.status = 'active'
          AND u.age_confirmed_at IS NOT NULL
      )
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.dm_mutual_ask(a_id int, b_id int)
    RETURNS boolean
    LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $fn$
      SELECT a_id <> b_id
         AND public.dm_reachable(a_id)
         AND public.dm_reachable(b_id)
         AND public.dm_can_ask(a_id, b_id)
         AND public.dm_can_ask(b_id, a_id)
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.dm_apparent_permission(target_id int)
    RETURNS text
    LANGUAGE plpgsql STABLE PARALLEL SAFE SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $fn$
    DECLARE
      actor_id int := NULLIF(current_setting('app.current_user_id', true), '')::int;
    BEGIN
      IF actor_id IS NULL THEN
        RAISE EXCEPTION 'dm_apparent_permission requires app.current_user_id';
      END IF;
      IF NOT public.dm_mutual_ask(actor_id, target_id) THEN
        RETURN 'denied';
      END IF;
      IF EXISTS (
        SELECT 1 FROM public.contact_grants g
        WHERE g.user_id_low = LEAST(actor_id, target_id)
          AND g.user_id_high = GREATEST(actor_id, target_id)
          AND g.kind = 'message'
          AND g.state = 'accepted'
      ) THEN
        RETURN 'open';
      END IF;
      RETURN 'may_request';
    END;
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.dm_listable_in_guild(target_guild_id int)
    RETURNS SETOF int
    LANGUAGE plpgsql STABLE PARALLEL SAFE SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $fn$
    DECLARE
      viewer_id int := NULLIF(current_setting('app.current_user_id', true), '')::int;
    BEGIN
      IF viewer_id IS NULL THEN
        RAISE EXCEPTION 'dm_listable_in_guild requires app.current_user_id';
      END IF;
      -- The viewer's own gates decide the whole answer, so they are asked once
      -- rather than once per member.
      IF NOT public.dm_reachable(viewer_id) THEN
        RETURN;
      END IF;
      RETURN QUERY
        SELECT m.user_id
        FROM public.guild_memberships m
        WHERE m.guild_id = target_guild_id
          AND m.user_id <> viewer_id
          AND NOT EXISTS (
            SELECT 1 FROM public.user_ignores i
            WHERE i.user_id = viewer_id AND i.ignored_user_id = m.user_id
          )
          AND public.dm_mutual_ask(viewer_id, m.user_id);
    END;
    $fn$
    """,
]

#: What the reader may see, and no more. Column-scoped where the table holds
#: anything beyond what the rule reads.
_READER_GRANTS = [
    "GRANT SELECT (id, status, age_confirmed_at) ON TABLE public.users TO {r}",
    "GRANT SELECT (id, status) ON TABLE public.guilds TO {r}",
    "GRANT SELECT (user_id, guild_id) ON TABLE public.guild_memberships TO {r}",
    "GRANT SELECT ON TABLE public.user_dm_settings TO {r}",
    "GRANT SELECT ON TABLE public.user_dm_guild_optouts TO {r}",
    "GRANT SELECT ON TABLE public.contact_grants TO {r}",
    "GRANT SELECT ON TABLE public.user_ignores TO {r}",
]

#: All rows of each, for the reader only.
_READER_POLICIES = [
    ("users", "dm_reader_read"),
    ("guilds", "dm_reader_read"),
    ("guild_memberships", "dm_reader_read"),
    ("user_dm_settings", "dm_reader_read"),
    ("user_dm_guild_optouts", "dm_reader_read"),
    ("contact_grants", "dm_reader_read"),
    ("user_ignores", "dm_reader_read"),
]


def upgrade() -> None:
    base = _platform_base()
    request_roles = f'app_guild_base, "{base}", app_user'

    _create_tables()

    # The starting policy a newly created account is given. The enum was
    # created with ``user_dm_settings`` just above, so this reuses it.
    op.add_column(
        "app_settings",
        sa.Column(
            "default_dm_policy",
            postgresql.ENUM(
                "private",
                "community",
                "public",
                name="user_dm_policy",
                create_type=False,
            ),
            nullable=False,
            server_default="private",
        ),
    )

    # Every existing account gets ``private`` rather than the operator default:
    # an account that predates the feature chose nothing, and the closed value
    # is the only one it can be given. This runs before RLS is forced on, while
    # the migration's own role can still write the rows.
    conn = op.get_bind()
    conn.execute(
        text(
            "INSERT INTO public.user_dm_settings "
            "(user_id, dm_policy, created_at, updated_at) "
            "SELECT id, 'private', now(), now() FROM public.users"
        )
    )
    seeded = conn.execute(
        text("SELECT count(*) FROM public.user_dm_settings")
    ).scalar_one()
    accounts = conn.execute(text("SELECT count(*) FROM public.users")).scalar_one()
    if seeded != accounts:
        raise RuntimeError(
            f"user_dm_settings backfill covered {seeded} of {accounts} accounts"
        )

    statements: list[str] = []
    for table in _TABLES:
        qualified = f"public.{table}"
        statements += [
            f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY",
            # The schema's default privileges hand every new public table to the
            # routed base roles, so they are wound back before anything is given.
            f"REVOKE ALL ON TABLE {qualified} FROM {request_roles}",
            f'GRANT SELECT, INSERT, DELETE ON TABLE {qualified} TO "{base}"',
        ]
    # Only these two are ever edited in place: a policy is changed, and a
    # pending grant becomes accepted.
    statements += [
        f'GRANT UPDATE ON TABLE public.user_dm_settings TO "{base}"',
        f'GRANT UPDATE ON TABLE public.contact_grants TO "{base}"',
    ]

    # Own-row policies. ``contact_grants`` names both parties on the row, so
    # "own" there means either side of the pair.
    own_row = {
        "user_dm_settings": f"user_id = {_USER_ID}",
        "user_dm_guild_optouts": f"user_id = {_USER_ID}",
        "contact_grants": (f"(user_id_low = {_USER_ID} OR user_id_high = {_USER_ID})"),
        "user_ignores": f"user_id = {_USER_ID}",
    }
    for table, predicate in own_row.items():
        qualified = f"public.{table}"
        for command in ("SELECT", "INSERT", "DELETE"):
            clause = "WITH CHECK" if command == "INSERT" else "USING"
            statements += [
                f"DROP POLICY IF EXISTS {table}_self_{command.lower()} ON {qualified}",
                f"CREATE POLICY {table}_self_{command.lower()} ON {qualified} "
                f'AS PERMISSIVE FOR {command} TO "{base}" '
                f"{clause} ({predicate})",
            ]
    for table in ("user_dm_settings", "contact_grants"):
        qualified = f"public.{table}"
        predicate = own_row[table]
        statements += [
            f"DROP POLICY IF EXISTS {table}_self_update ON {qualified}",
            f"CREATE POLICY {table}_self_update ON {qualified} "
            f'AS PERMISSIVE FOR UPDATE TO "{base}" '
            f"USING ({predicate}) WITH CHECK ({predicate})",
        ]

    # The system engine: seeding a new account's policy row, the lifecycle
    # sweeps, and clearing an erased account off these tables.
    statements += [
        "GRANT SELECT, INSERT, DELETE ON TABLE public.user_dm_settings TO app_admin",
        "GRANT SELECT, DELETE ON TABLE public.user_dm_guild_optouts TO app_admin",
        "GRANT SELECT, DELETE ON TABLE public.contact_grants TO app_admin",
        "GRANT SELECT, DELETE ON TABLE public.user_ignores TO app_admin",
    ]

    # The reader role and the rule it owns.
    statements += [
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{READER}') THEN
                CREATE ROLE "{READER}" NOLOGIN;
            END IF;
        END $$;
        """,
        # Migrations run as ``app_provisioner``, not as a superuser, and handing
        # an object to a role means being able to become it.
        f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE',
        f'GRANT USAGE ON SCHEMA public TO "{READER}"',
    ]
    statements += [grant.format(r=f'"{READER}"') for grant in _READER_GRANTS]
    for table, policy in _READER_POLICIES:
        statements += [
            f"DROP POLICY IF EXISTS {policy} ON public.{table}",
            f"CREATE POLICY {policy} ON public.{table} "
            f'AS PERMISSIVE FOR SELECT TO "{READER}" USING (true)',
        ]
    statements += _FUNCTIONS
    # Ownership can only be handed to a role that may create in the schema.
    # Given for the assignment and taken straight back: the reader creates
    # nothing, it only reads.
    statements.append(f'GRANT CREATE ON SCHEMA public TO "{READER}"')
    for function, signature in (
        ("dm_can_ask", "int, int"),
        ("dm_reachable", "int"),
        ("dm_mutual_ask", "int, int"),
        ("dm_apparent_permission", "int"),
        ("dm_listable_in_guild", "int"),
    ):
        statements += [
            f'ALTER FUNCTION public.{function}({signature}) OWNER TO "{READER}"',
            f"REVOKE ALL ON FUNCTION public.{function}({signature}) FROM PUBLIC",
        ]
    statements.append(f'REVOKE CREATE ON SCHEMA public FROM "{READER}"')
    # Only the two entry points are callable, and only from the platform path.
    # The three below them are reached by the pair that owns them.
    statements += [
        f'GRANT EXECUTE ON FUNCTION public.dm_apparent_permission(int) TO "{base}"',
        f'GRANT EXECUTE ON FUNCTION public.dm_listable_in_guild(int) TO "{base}"',
    ]

    _run(statements)


def downgrade() -> None:
    statements = []
    for function, signature in (
        ("dm_listable_in_guild", "int"),
        ("dm_apparent_permission", "int"),
        ("dm_mutual_ask", "int, int"),
        ("dm_reachable", "int"),
        ("dm_can_ask", "int, int"),
    ):
        statements.append(f"DROP FUNCTION IF EXISTS public.{function}({signature})")
    for table, policy in _READER_POLICIES:
        statements.append(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
    statements += [
        f'REVOKE ALL ON TABLE public.users FROM "{READER}"',
        f'REVOKE ALL ON TABLE public.guilds FROM "{READER}"',
        f'REVOKE ALL ON TABLE public.guild_memberships FROM "{READER}"',
        f'REVOKE ALL ON SCHEMA public FROM "{READER}"',
    ]
    for table in _TABLES:
        qualified = f"public.{table}"
        for command in ("select", "insert", "delete", "update"):
            statements.append(
                f"DROP POLICY IF EXISTS {table}_self_{command} ON {qualified}"
            )
        statements.append(f"ALTER TABLE {qualified} DISABLE ROW LEVEL SECURITY")
    _run(statements)

    op.drop_index("ix_user_ignores_ignored_user", table_name="user_ignores")
    op.drop_table("user_ignores")
    op.drop_index("ix_contact_grants_user_high", table_name="contact_grants")
    op.drop_table("contact_grants")
    op.drop_table("user_dm_guild_optouts")
    op.drop_column("app_settings", "default_dm_policy")
    op.drop_table("user_dm_settings")
    _run(
        [
            "DROP TYPE IF EXISTS contact_grant_state",
            "DROP TYPE IF EXISTS contact_grant_kind",
            "DROP TYPE IF EXISTS user_dm_policy",
            # The role is cluster-global, so another database may still grant to
            # it; that is somebody else's grant to give up.
            f"""
            DO $$
            BEGIN
                DROP ROLE IF EXISTS "{READER}";
            EXCEPTION WHEN dependent_objects_still_exist THEN
                NULL;
            END
            $$
            """,
        ]
    )
