"""add_is_archived_to_tasks

Revision ID: 8bab3c8344af
Revises: 20260113_0018
Create Date: 2026-01-13

"""

revision = "8bab3c8344af"
down_revision = "20260113_0018"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("is_archived", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index("ix_tasks_is_archived", "tasks", ["is_archived"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_is_archived", table_name="tasks")
    op.drop_column("tasks", "is_archived")
