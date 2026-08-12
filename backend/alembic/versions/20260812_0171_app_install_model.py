"""app install model: artifacts, config custody, per-member connections

Three changes to how a guild's installed apps are recorded.

``guild_apps.artifacts`` replaces the assumption that an install produces at
most one thing recorded under a well-known ``config`` key. It is a list of
``{"type": …, "id": …}``, so an install may produce several and removal walks
the list through a per-type handler. The existing tool-instance rows carry their
calendar id under ``config.calendar_id``; they are rewritten into the new shape
here and the old key is dropped, so there is one place a caller looks.

``guild_apps.config_secrets`` / ``config_state`` make the row a credential
custodian: per-key Fernet ciphertexts for what a guild admin typed into an app's
connection form, plus what the app reported back about whether that
configuration actually works.

``guild_app_user_connections`` is new — one row per (install, connection,
member) for the vendors that authorize a person rather than an organization.
Guild-level (an app belongs to the guild, not to any initiative), so it carries
no initiative RLS; rows belong to one member, so it carries the same
``own_row_*`` policies the other member-owned guild tables use: the owner, or
the guild admin whose authority covers everything in their guild. The policies
are written out here as well as being rendered at provisioning time, so the
table is never reachable without them between this migration and the next boot.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260812_0171"
down_revision = "20260812_0168"
branch_labels = None
depends_on = None


#: Move a tool-instance install's calendar id into ``artifacts``.
#:
#: Guarded on the pinned definition's tool rather than on the key alone, so a
#: coincidental ``calendar_id`` in some other app's config is left where it is.
#: Only rows that have not been migrated already are touched, which makes a
#: re-run a no-op.
_MIGRATE_ARTIFACTS = """
UPDATE guild_apps
SET artifacts = jsonb_build_array(
        jsonb_build_object(
            'type', 'calendar',
            'id', (config ->> 'calendar_id')::int
        )
    ),
    config = config - 'calendar_id'
WHERE definition ->> 'tool' = 'calendar'
  AND jsonb_typeof(config -> 'calendar_id') = 'number'
  AND artifacts = '[]'::jsonb
"""

#: The reverse: put the id back under the config key it came from.
_UNMIGRATE_ARTIFACTS = """
UPDATE guild_apps
SET config = config || jsonb_build_object(
        'calendar_id', (artifacts -> 0 ->> 'id')::int
    ),
    artifacts = '[]'::jsonb
WHERE jsonb_typeof(artifacts) = 'array'
  AND jsonb_array_length(artifacts) = 1
  AND artifacts -> 0 ->> 'type' = 'calendar'
"""

#: Owner-or-guild-admin, matching the rendered own-row predicate exactly (see
#: ``app.db.guild_ddl._OWN_ROW_PREDICATE``). The cast is NULLIF-guarded because
#: an unset context leaves the setting empty and a bare ``''::int`` would raise
#: for every row the policy is evaluated against.
_OWN_ROW_PREDICATE = (
    "(user_id = NULLIF(current_setting('app.current_user_id'::text, true), '')::int"
    " OR current_setting('app.current_guild_role'::text, true) = 'admin'::text)"
)

_OWN_ROW_POLICIES = (
    ("own_row_select", "SELECT", "USING"),
    ("own_row_insert", "INSERT", "WITH CHECK"),
    ("own_row_update", "UPDATE", "USING-CHECK"),
    ("own_row_delete", "DELETE", "USING"),
)

_CONNECTIONS_TABLE = "guild_app_user_connections"


def _own_row_rls_statements() -> list[str]:
    statements = [
        f"ALTER TABLE {_CONNECTIONS_TABLE} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {_CONNECTIONS_TABLE} FORCE ROW LEVEL SECURITY",
    ]
    for name, command, clause in _OWN_ROW_POLICIES:
        statements.append(f"DROP POLICY IF EXISTS {name} ON {_CONNECTIONS_TABLE}")
        head = (
            f"CREATE POLICY {name} ON {_CONNECTIONS_TABLE} AS PERMISSIVE FOR {command}"
        )
        if clause == "USING-CHECK":
            statements.append(
                f"{head} USING ({_OWN_ROW_PREDICATE}) WITH CHECK ({_OWN_ROW_PREDICATE})"
            )
        elif clause == "WITH CHECK":
            statements.append(f"{head} WITH CHECK ({_OWN_ROW_PREDICATE})")
        else:
            statements.append(f"{head} USING ({_OWN_ROW_PREDICATE})")
    return statements


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("guild_apps", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "config_secrets",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="{}",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "config_state",
                sa.String(length=16),
                server_default="unverified",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("config_state_detail", sa.String(length=120), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "artifacts",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="[]",
                nullable=False,
            )
        )

    # Existing installs move to the new shape in the same step that adds it, so
    # no row is ever read through code that expects one and finds the other.
    op.execute(sa.text(_MIGRATE_ARTIFACTS))

    op.create_table(
        _CONNECTIONS_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("connection_ref", sa.String(length=32), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "config_secrets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("account_label", sa.Text(), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["app_id"], ["guild_apps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "app_id",
            "connection_id",
            "user_id",
            name="guild_app_user_connections_unique_member",
        ),
        sa.UniqueConstraint(
            "connection_ref", name="guild_app_user_connections_unique_ref"
        ),
    )
    with op.batch_alter_table(_CONNECTIONS_TABLE, schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_guild_app_user_connections_guild_id"),
            ["guild_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_guild_app_user_connections_app_id"),
            ["app_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_guild_app_user_connections_user_id"),
            ["user_id"],
            unique=False,
        )

    for statement in _own_row_rls_statements():
        op.execute(sa.text(statement))


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    for name, _command, _clause in _OWN_ROW_POLICIES:
        op.execute(sa.text(f"DROP POLICY IF EXISTS {name} ON {_CONNECTIONS_TABLE}"))
    op.execute(sa.text(f"ALTER TABLE {_CONNECTIONS_TABLE} DISABLE ROW LEVEL SECURITY"))

    with op.batch_alter_table(_CONNECTIONS_TABLE, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_guild_app_user_connections_user_id"))
        batch_op.drop_index(batch_op.f("ix_guild_app_user_connections_app_id"))
        batch_op.drop_index(batch_op.f("ix_guild_app_user_connections_guild_id"))
    op.drop_table(_CONNECTIONS_TABLE)

    op.execute(sa.text(_UNMIGRATE_ARTIFACTS))

    with op.batch_alter_table("guild_apps", schema=None) as batch_op:
        batch_op.drop_column("artifacts")
        batch_op.drop_column("config_state_detail")
        batch_op.drop_column("config_state")
        batch_op.drop_column("config_secrets")
