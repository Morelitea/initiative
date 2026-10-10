"""a member's secrets are theirs

``ai_member_key_secrets`` and ``plugin_connection_secrets``, in every guild
schema: the key a member gave an AI connection, and the values their
connection to a plug-in's vendor holds, each beside the row that says the
credential exists. Each is moved in, and ``guild_ai_member_keys.api_key_encrypted``
and ``guild_plugin_user_connections.config_secrets`` are dropped.

``guild_plugin_user_connections.secret_fields`` takes the place of the values
on the connection row: which keys hold one, and a digest of each. It is filled
here from the values being moved; from then on
``tr_plugin_connection_secrets_fields`` keeps it in step. The policies, the
trigger and its function (``public.fn_plugin_connection_secret_fields()``) are
rendered by the provisioning run.

The downgrade puts the values back on the rows they came from.

Revision ID: 20261010_0486
Revises: 20261010_0485
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261010_0486"
down_revision = "20261010_0485"
branch_labels = None
depends_on = None

KEYS = "guild_ai_member_keys"
KEY_SECRETS = "ai_member_key_secrets"
CONNECTIONS = "guild_plugin_user_connections"
CONNECTION_SECRETS = "plugin_connection_secrets"

#: Which keys of a values map hold a value, with a digest of each — what the
#: trigger writes.
_FIELDS = (
    "(SELECT COALESCE(jsonb_object_agg("
    "f.key, encode(sha256(convert_to(f.value, 'UTF8')), 'hex')), '{{}}'::jsonb)"
    " FROM jsonb_each_text({values}) f)"
)


def _forced(bind, tables: tuple[str, ...]) -> list[str]:
    """The tables of ``tables`` that force RLS on their owner here."""
    return [
        table
        for table in tables
        if bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    ]


def _unforced(bind, tables: tuple[str, ...], write) -> None:
    """Run ``write`` with the owner's RLS lifted and the user triggers held on
    ``tables``, both restored after."""
    forced = _forced(bind, tables)
    for table in forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for table in tables:
        op.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        write()
    finally:
        for table in tables:
            op.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        for table in forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply_upgrade(bind))


def _move_in(bind) -> None:
    bind.execute(
        sa.text(
            f"INSERT INTO {KEY_SECRETS} (key_id, api_key_encrypted) "
            f"SELECT id, api_key_encrypted FROM {KEYS}"
        )
    )
    bind.execute(
        sa.text(
            f"INSERT INTO {CONNECTION_SECRETS} (connection_row_id, secrets) "
            f"SELECT id, config_secrets FROM {CONNECTIONS} "
            "WHERE config_secrets <> '{}'::jsonb"
        )
    )
    bind.execute(
        sa.text(
            f"UPDATE {CONNECTIONS} SET secret_fields = "
            + _FIELDS.format(values="config_secrets")
            + " WHERE config_secrets <> '{}'::jsonb"
        )
    )


def _apply_upgrade(bind) -> None:
    op.create_table(
        KEY_SECRETS,
        sa.Column("key_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("api_key_encrypted", sa.String(length=2000), nullable=False),
        sa.ForeignKeyConstraint(["key_id"], [f"{KEYS}.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("key_id"),
    )
    op.create_table(
        CONNECTION_SECRETS,
        sa.Column(
            "connection_row_id", sa.Integer(), autoincrement=False, nullable=False
        ),
        sa.Column(
            "secrets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_row_id"], [f"{CONNECTIONS}.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("connection_row_id"),
    )
    op.add_column(
        CONNECTIONS,
        sa.Column(
            "secret_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    _unforced(bind, (KEYS, CONNECTIONS), lambda: _move_in(bind))
    op.drop_column(KEYS, "api_key_encrypted")
    op.drop_column(CONNECTIONS, "config_secrets")
    for table in (KEY_SECRETS, CONNECTION_SECRETS):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply_downgrade(bind))
    op.execute("DROP FUNCTION IF EXISTS public.fn_plugin_connection_secret_fields()")


def _move_out(bind) -> None:
    bind.execute(
        sa.text(
            f"UPDATE {KEYS} k SET api_key_encrypted = s.api_key_encrypted "
            f"FROM {KEY_SECRETS} s WHERE s.key_id = k.id"
        )
    )
    # A key row whose key was never kept has nothing to say; the old shape
    # had no such row.
    bind.execute(sa.text(f"DELETE FROM {KEYS} WHERE api_key_encrypted IS NULL"))
    bind.execute(
        sa.text(
            f"UPDATE {CONNECTIONS} c SET config_secrets = s.secrets "
            f"FROM {CONNECTION_SECRETS} s WHERE s.connection_row_id = c.id"
        )
    )


def _apply_downgrade(bind) -> None:
    # What the provisioning run rendered onto the credential rows; the older
    # code renders its own policies there at the next boot.
    for table in (KEYS, CONNECTIONS):
        for verb in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS member_credential_{verb} ON {table}")
    op.add_column(
        KEYS, sa.Column("api_key_encrypted", sa.String(length=2000), nullable=True)
    )
    op.add_column(
        CONNECTIONS,
        sa.Column(
            "config_secrets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    _unforced(
        bind,
        (KEYS, CONNECTIONS, KEY_SECRETS, CONNECTION_SECRETS),
        lambda: _move_out(bind),
    )
    op.alter_column(KEYS, "api_key_encrypted", nullable=False)
    op.drop_column(CONNECTIONS, "secret_fields")
    # Named in the schema being walked, never resolved through the search
    # path's fallback to ``public``. Policies and triggers go with the tables.
    for table in (KEY_SECRETS, CONNECTION_SECRETS):
        op.execute(
            "DO $$ BEGIN EXECUTE format("
            f"'DROP TABLE IF EXISTS %I.{table}', current_schema()); END $$;"
        )
