"""per-tool comment switch

Every tool carries ``comments_disabled`` — the advanced setting that takes its
comment thread off the tool's page. It defaults to false so every existing
project, document, queue, counter group, calendar, and dashboard keeps the
thread it has, and turning one off is an explicit action after upgrade.

Tasks are unaffected: their thread is part of the task flow, not the tool
surface, and ``comments.task_id`` has no switch.

Revision ID: 20260831_0206
Revises: 20260829_0205
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260831_0206"
down_revision = "20260829_0205"
branch_labels = None
depends_on = None

# The tool content tables, in Tool enum order.
_TOOL_TABLES = (
    "projects",
    "documents",
    "queues",
    "counter_groups",
    "calendars",
    "dashboards",
)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    for table in _TOOL_TABLES:
        op.add_column(
            table,
            sa.Column(
                "comments_disabled",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    for table in _TOOL_TABLES:
        op.drop_column(table, "comments_disabled")
