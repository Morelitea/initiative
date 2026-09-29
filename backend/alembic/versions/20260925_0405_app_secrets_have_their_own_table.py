"""app secrets have their own table

``guild_app_secrets``, in every guild schema: one row per install holding the
secret values of its connections, ``{connection_id: {key: ciphertext}}``, as
``guild_apps.config_secrets`` held them. Each install's non-empty map is moved
in, and ``guild_apps.config_secrets`` is dropped.

``guild_apps.secret_fields`` takes its place on the install row: the same
connection and field keys, each holding the SHA-256 hex digest of its
ciphertext. It is filled here from the values being moved; from then on
``tr_guild_app_secrets_fields`` keeps it in step. The policies, the trigger and
its function (``public.fn_app_secret_fields()``) are rendered by the
provisioning run.

The downgrade restores ``guild_apps.config_secrets`` from the table.

Revision ID: 20260925_0405
Revises: 20260925_0404
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260925_0405"
down_revision = "20260925_0404"
branch_labels = None
depends_on = None

SECRETS = "guild_app_secrets"

#: ``secret_fields`` for a map of secret values ``{secrets}``: the same keys,
#: each holding the SHA-256 hex digest of its ciphertext.
_FIELDS_OF = """(
    SELECT COALESCE(jsonb_object_agg(c.key, (
        SELECT COALESCE(jsonb_object_agg(
            f.key, encode(sha256(convert_to(f.value, 'UTF8')), 'hex')
        ), '{{}}'::jsonb)
        FROM jsonb_each_text(c.value) f
    )), '{{}}'::jsonb)
    FROM jsonb_each({secrets}) c
    WHERE jsonb_typeof(c.value) = 'object'
)"""


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
    triggers on ``guild_apps`` held, both restored after."""
    forced = _forced(bind, tables)
    for table in forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE guild_apps DISABLE TRIGGER USER")
    try:
        write()
    finally:
        op.execute("ALTER TABLE guild_apps ENABLE TRIGGER USER")
        for table in forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply_upgrade(bind))


def _move_in(bind) -> None:
    bind.execute(
        sa.text(
            "INSERT INTO guild_app_secrets (install_id, secrets) "
            "SELECT id, config_secrets FROM guild_apps "
            "WHERE config_secrets <> '{}'::jsonb"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE guild_apps SET secret_fields = "
            + _FIELDS_OF.format(secrets="config_secrets")
            + " WHERE config_secrets <> '{}'::jsonb"
        )
    )


def _apply_upgrade(bind) -> None:
    op.create_table(
        SECRETS,
        sa.Column("install_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column(
            "secrets",
            postgresql.JSONB(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["install_id"], ["guild_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("install_id"),
    )
    op.add_column(
        "guild_apps",
        sa.Column(
            "secret_fields",
            postgresql.JSONB(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    _unforced(bind, ("guild_apps",), lambda: _move_in(bind))
    op.drop_column("guild_apps", "config_secrets")
    op.execute("ALTER TABLE guild_app_secrets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE guild_app_secrets FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply_downgrade(bind))
    op.execute("DROP FUNCTION IF EXISTS public.fn_app_secret_fields()")


def _move_out(bind) -> None:
    bind.execute(
        sa.text(
            "UPDATE guild_apps a SET config_secrets = s.secrets "
            "FROM guild_app_secrets s WHERE s.install_id = a.id"
        )
    )


def _apply_downgrade(bind) -> None:
    op.add_column(
        "guild_apps",
        sa.Column(
            "config_secrets",
            postgresql.JSONB(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    _unforced(bind, ("guild_apps", SECRETS), lambda: _move_out(bind))
    op.drop_column("guild_apps", "secret_fields")
    # Named in the schema being walked, never resolved through the search
    # path's fallback to ``public``. Policies and the trigger go with the table.
    op.execute(
        "DO $$ BEGIN EXECUTE format("
        f"'DROP TABLE IF EXISTS %I.{SECRETS}', current_schema()); END $$;"
    )
