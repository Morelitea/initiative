"""A credential lives as long as its import.

``import_credentials`` carries the secret an import job needs to read a
foreign site from the request that collected it to the worker that picks the
job up, and holds it no longer than that: the lifecycle service deletes the
row when the job reaches a terminal state, is cancelled, or ages out. There is
no saved-connection surface behind it — no list, no edit screen, no rotation,
no reuse across jobs.

It lives in ``public`` because it is written before any guild schema is routed
into and read on the system engine. It names a guild without being that
guild's content.

app_admin-only: RLS enabled and forced with no policies, which is the
strictest state a table has and the right one here, since no request-path role
ever reads a row back — and the schema's default grants come straight off the
two base roles. The table is new and empty, so there is nothing to backfill
and no DML to order against the lockdown.

Revision ID: 20260920_0335
Revises: 20260920_0334
Create Date: 2026-09-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260920_0335"
down_revision = "20260920_0334"
branch_labels = None
depends_on = None


TABLE = "import_credentials"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
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
    # The sweep reads it.
    op.create_index(f"ix_{TABLE}_expires_at", TABLE, ["expires_at"])

    if not _is_postgres():
        return

    base = _platform_base()
    for statement in (
        f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
        # The public schema default-grants platform_base + app_guild_base full
        # DML on every new table; both come straight back off.
        f'REVOKE ALL ON TABLE public.{TABLE} FROM app_guild_base, "{base}"',
        # No UPDATE: a one-shot value is replaced by a new row, never rotated
        # in place.
        f"GRANT SELECT, INSERT, DELETE ON TABLE public.{TABLE} TO app_admin",
        f'REVOKE ALL ON SEQUENCE public.{TABLE}_id_seq FROM app_guild_base, "{base}"',
        f"GRANT USAGE, SELECT ON SEQUENCE public.{TABLE}_id_seq TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS public.{TABLE} CASCADE")
