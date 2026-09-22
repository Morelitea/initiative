"""A secret is a field of its job, not a table of its own.

``import_credentials`` held one value — the token a fetch needs to read a
foreign site — for one job, for the length of that job. It was never updated,
never listed, and never read except by the id its own job quoted: a column's
worth of facts given a table, a model, a module, a sweep and a row in five
grant registries.

It also sat in ``public``, holding a community's secret outside that
community's schema. The justification for that was the write happening before
a guild schema was routed into, which the connect endpoint has not done for
some time — it takes a guild context like every other import route.

So the value moves onto ``import_jobs.secret_encrypted``, which already lives
in the guild's own schema, already carries the job's deadline, and already
dies when the job does. The connect step now proves a token and keeps
nothing; the request that starts an import carries it again, and that one has
a row to put it on.

Both halves are here because they are one move: the column is added to
``guild_template`` and every ``guild_<id>``, and the shared table goes.
Anything still in it belonged to a job that will be re-started, and the
downgrade rebuilds the table empty.

Revision ID: 20260922_0353
Revises: 20260922_0352
Create Date: 2026-09-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings
from app.db.guild_migrations import guild_schema_names

revision = "20260922_0353"
down_revision = "20260922_0352"
branch_labels = None
depends_on = None


TABLE = "import_credentials"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    connection = op.get_bind()
    for schema in guild_schema_names(connection):
        connection.execute(
            sa.text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        connection.execute(
            sa.text(
                "ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS secret_encrypted TEXT"
            )
        )
    connection.execute(sa.text("SELECT set_config('search_path', 'public', true)"))

    op.execute(f"DROP TABLE IF EXISTS public.{TABLE} CASCADE")


def downgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("site_url", sa.Text(), nullable=False),
        sa.Column("principal", sa.Text(), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(f"ix_{TABLE}_guild_id", TABLE, ["guild_id"])
    op.create_index(f"ix_{TABLE}_expires_at", TABLE, ["expires_at"])

    if _is_postgres():
        base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
        for statement in (
            f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
            f'REVOKE ALL ON TABLE public.{TABLE} FROM app_guild_base, "{base}"',
            f"GRANT SELECT, INSERT, DELETE ON TABLE public.{TABLE} TO app_admin",
            f'REVOKE ALL ON SEQUENCE public.{TABLE}_id_seq FROM app_guild_base, "{base}"',
            f"GRANT USAGE, SELECT ON SEQUENCE public.{TABLE}_id_seq TO app_admin",
        ):
            op.execute(statement)

    connection = op.get_bind()
    for schema in guild_schema_names(connection):
        connection.execute(
            sa.text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        connection.execute(
            sa.text("ALTER TABLE import_jobs DROP COLUMN IF EXISTS secret_encrypted")
        )
    connection.execute(sa.text("SELECT set_config('search_path', 'public', true)"))
