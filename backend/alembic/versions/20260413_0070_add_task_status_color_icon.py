"""Add color and icon columns to task_statuses.

Adds customizable color and icon fields to task statuses, with values
backfilled from each row's category using the same defaults the service
layer applies to newly created statuses.

Revision ID: 20260413_0070
Revises: 20260409_0069
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "20260413_0070"
down_revision = "20260409_0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column(
        "task_statuses",
        sa.Column("color", sa.String(length=9), nullable=True),
    )
    op.add_column(
        "task_statuses",
        sa.Column("icon", sa.String(length=64), nullable=True),
    )

    conn.execute(
        text(
            """
            UPDATE task_statuses
            SET color = CASE category
                    WHEN 'backlog' THEN '#94A3B8'
                    WHEN 'todo' THEN '#FBBF24'
                    WHEN 'in_progress' THEN '#60A5FA'
                    WHEN 'done' THEN '#34D399'
                END,
                icon = CASE category
                    WHEN 'backlog' THEN 'circle-dashed'
                    WHEN 'todo' THEN 'circle-pause'
                    WHEN 'in_progress' THEN 'circle-play'
                    WHEN 'done' THEN 'circle-check'
                END
            WHERE color IS NULL OR icon IS NULL
            """
        )
    )

    op.alter_column(
        "task_statuses",
        "color",
        existing_type=sa.String(length=9),
        nullable=False,
        server_default="'#94A3B8'",
    )
    op.alter_column(
        "task_statuses",
        "icon",
        existing_type=sa.String(length=64),
        nullable=False,
        server_default="'circle-dashed'",
    )


def downgrade() -> None:
    op.drop_column("task_statuses", "icon")
    op.drop_column("task_statuses", "color")
