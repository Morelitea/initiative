"""apps keep schedules

``app_schedule_runs``, in every guild schema: one row for each schedule an
install's pinned definition declares, with when its call last succeeded, when
it is next due, how many calls have failed since, and the lease a worker holds
while it calls the app. No pinned definition declares a schedule yet, since
the normalizer dropped the term, so there is nothing to carry in.

The policies are rendered from the registries at boot.

Revision ID: 20260925_0402
Revises: 20260925_0401
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260925_0402"
down_revision = "20260925_0401"
branch_labels = None
depends_on = None

RUNS = "app_schedule_runs"


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _create)


def _create() -> None:
    op.create_table(
        RUNS,
        sa.Column("install_id", sa.Integer(), nullable=False),
        sa.Column("schedule_id", sa.String(length=64), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["install_id"], ["guild_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("install_id", "schedule_id"),
    )
    op.execute(f"ALTER TABLE {RUNS} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {RUNS} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop)


def _drop() -> None:
    # Named in the schema being walked, never resolved through the search
    # path's fallback to ``public``. Policies go with the table.
    op.execute(
        "DO $$ BEGIN EXECUTE format("
        f"'DROP TABLE IF EXISTS %I.{RUNS}', current_schema()); END $$;"
    )
