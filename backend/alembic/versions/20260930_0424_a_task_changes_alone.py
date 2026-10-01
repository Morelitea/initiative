"""a task in a repeating series can change alone

``series_id`` names the first task of the repeating series a task is in, so
every task of a series can be found, past and current. It is a name rather
than a key: the series goes on when its first task is purged.
``recurrence_carry`` holds what an edit of just this task changed from, and the
next task in the series is made with those values.

Revision ID: 20260930_0424
Revises: 20260930_0423
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260930_0424"
down_revision = "20260930_0423"
branch_labels = None
depends_on = None


def _add() -> None:
    op.add_column("tasks", sa.Column("series_id", sa.Integer(), nullable=True))
    op.add_column(
        "tasks",
        sa.Column(
            "recurrence_carry", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.create_index("ix_tasks_series_id", "tasks", ["series_id"])


def _drop() -> None:
    op.drop_index("ix_tasks_series_id", table_name="tasks")
    op.drop_column("tasks", "recurrence_carry")
    op.drop_column("tasks", "series_id")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _add)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop)
