"""grants report to their case

``access_grants`` gains the operations case a grant serves
(``case_task_id``, a weak ref to a task in the operations community), and
when its case was last told what it did (``activity_noted_at``) and told it
had ended (``closed_out_at``).

``public.access_grant_activity`` holds one row per request served through a
grant: the route template, the status, whether it wrote, and the kind and id
of the thing it named — ids and templates, never content. It is the system
engine's alone: ``app_admin`` adds, reads and deletes rows; the login role and
the guild and platform floors, which the schema default grants full DML on a
new table, are revoked, from the table and its sequence; RLS is enabled and
forced with no policies (``FORCED_NO_POLICY`` in ``app.db.public_rls``).

The table is new and has nothing to carry, so it is created and then locked.
Every grant that already ended is closed out, so its case is not told of it
now.

Revision ID: 20261010_0489
Revises: 20261010_0488
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261010_0489"
down_revision = "20261010_0488"
branch_labels = None
depends_on = None

TABLE = "access_grant_activity"


#: Grants that ended before any could report to a case have nothing to report,
#: so each is closed out. Row security binds this table's owner too, so it is
#: lifted for the write and put back.
CLOSE_OUT_ENDED = (
    "ALTER TABLE public.access_grants NO FORCE ROW LEVEL SECURITY",
    "UPDATE public.access_grants SET closed_out_at = now() "
    "WHERE status <> 'approved' OR expires_at <= now()",
    "ALTER TABLE public.access_grants FORCE ROW LEVEL SECURITY",
)


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    op.add_column(
        "access_grants", sa.Column("case_task_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "access_grants",
        sa.Column("activity_noted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "access_grants",
        sa.Column("closed_out_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "grant_id",
            sa.Integer(),
            sa.ForeignKey("access_grants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("route", sa.String(length=256), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("is_write", sa.Boolean(), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        f"ix_{TABLE}_grant_occurred", TABLE, ["grant_id", "occurred_at"], unique=False
    )
    for statement in (
        f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
        f'REVOKE ALL ON TABLE public.{TABLE} FROM app_user, app_guild_base, "{_platform_base()}"',
        f'REVOKE ALL ON SEQUENCE public.{TABLE}_id_seq FROM app_user, app_guild_base, "{_platform_base()}"',
        f"GRANT SELECT, INSERT, DELETE ON TABLE public.{TABLE} TO app_admin",
        f"GRANT USAGE, SELECT ON SEQUENCE public.{TABLE}_id_seq TO app_admin",
    ):
        op.execute(statement)
    for statement in CLOSE_OUT_ENDED:
        op.execute(statement)


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.{TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_index(f"ix_{TABLE}_grant_occurred", table_name=TABLE)
    op.drop_table(TABLE)
    op.drop_column("access_grants", "closed_out_at")
    op.drop_column("access_grants", "activity_noted_at")
    op.drop_column("access_grants", "case_task_id")
