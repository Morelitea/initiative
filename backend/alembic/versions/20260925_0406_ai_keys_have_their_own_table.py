"""ai keys have their own table

``guild_ai_connection_keys``, in every guild schema: one row per guild AI
connection that has a shared key, holding the ciphertext
``guild_ai_connections.api_key_encrypted`` held. Each key is moved in, and
``guild_ai_connections.api_key_encrypted`` is dropped.

``guild_ai_connections.has_api_key`` takes its place on the connection row. It
is filled here from the keys being moved; from then on
``tr_guild_ai_connection_keys_present`` keeps it in step. The policies, the
trigger and its function (``public.fn_ai_connection_key_present()``) are
rendered by the provisioning run.

The downgrade restores ``guild_ai_connections.api_key_encrypted`` from the
table.

Revision ID: 20260925_0406
Revises: 20260925_0405
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260925_0406"
down_revision = "20260925_0405"
branch_labels = None
depends_on = None

KEYS = "guild_ai_connection_keys"
CONNECTIONS = "guild_ai_connections"


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
    """Run ``write`` with the owner's RLS lifted on ``tables`` and the user
    triggers on the connections held, both restored after."""
    forced = _forced(bind, tables)
    for table in forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {CONNECTIONS} DISABLE TRIGGER USER")
    try:
        write()
    finally:
        op.execute(f"ALTER TABLE {CONNECTIONS} ENABLE TRIGGER USER")
        for table in forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply_upgrade(bind))


def _move_in(bind) -> None:
    bind.execute(
        sa.text(
            f"INSERT INTO {KEYS} (connection_id, api_key_encrypted) "
            f"SELECT id, api_key_encrypted FROM {CONNECTIONS} "
            "WHERE api_key_encrypted IS NOT NULL"
        )
    )
    bind.execute(
        sa.text(
            f"UPDATE {CONNECTIONS} SET has_api_key = true "
            "WHERE api_key_encrypted IS NOT NULL"
        )
    )


def _apply_upgrade(bind) -> None:
    op.create_table(
        KEYS,
        sa.Column("connection_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("api_key_encrypted", sa.String(length=2000), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], [f"{CONNECTIONS}.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("connection_id"),
    )
    op.add_column(
        CONNECTIONS,
        sa.Column(
            "has_api_key",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    _unforced(bind, (CONNECTIONS,), lambda: _move_in(bind))
    op.drop_column(CONNECTIONS, "api_key_encrypted")
    op.execute(f"ALTER TABLE {KEYS} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {KEYS} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply_downgrade(bind))
    op.execute("DROP FUNCTION IF EXISTS public.fn_ai_connection_key_present()")


def _move_out(bind) -> None:
    bind.execute(
        sa.text(
            f"UPDATE {CONNECTIONS} c SET api_key_encrypted = k.api_key_encrypted "
            f"FROM {KEYS} k WHERE k.connection_id = c.id"
        )
    )


def _apply_downgrade(bind) -> None:
    op.add_column(
        CONNECTIONS,
        sa.Column("api_key_encrypted", sa.String(length=2000), nullable=True),
    )
    _unforced(bind, (CONNECTIONS, KEYS), lambda: _move_out(bind))
    op.drop_column(CONNECTIONS, "has_api_key")
    # Named in the schema being walked, never resolved through the search
    # path's fallback to ``public``. Policies and the trigger go with the table.
    op.execute(
        "DO $$ BEGIN EXECUTE format("
        f"'DROP TABLE IF EXISTS %I.{KEYS}', current_schema()); END $$;"
    )
