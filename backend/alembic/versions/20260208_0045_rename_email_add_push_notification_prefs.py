"""Rename notify_* to email_*, add push_* notification preference columns

Revision ID: 20260208_0045
Revises: 20260207_0044
Create Date: 2026-02-08
"""

from alembic import op
import sqlalchemy as sa

revision = "20260208_0045"
down_revision = "20260207_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename existing notify_* columns to email_*
    op.alter_column("users", "notify_initiative_addition", new_column_name="email_initiative_addition")
    op.alter_column("users", "notify_task_assignment", new_column_name="email_task_assignment")
    op.alter_column("users", "notify_project_added", new_column_name="email_project_added")
    op.alter_column("users", "notify_overdue_tasks", new_column_name="email_overdue_tasks")
    op.alter_column("users", "notify_mentions", new_column_name="email_mentions")

    # Add new push_* columns
    op.add_column("users", sa.Column("push_initiative_addition", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("push_task_assignment", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("push_project_added", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("push_overdue_tasks", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("push_mentions", sa.Boolean(), nullable=False, server_default="true"))


def downgrade() -> None:
    # Drop push_* columns
    op.drop_column("users", "push_mentions")
    op.drop_column("users", "push_overdue_tasks")
    op.drop_column("users", "push_project_added")
    op.drop_column("users", "push_task_assignment")
    op.drop_column("users", "push_initiative_addition")

    # Rename email_* back to notify_*
    op.alter_column("users", "email_initiative_addition", new_column_name="notify_initiative_addition")
    op.alter_column("users", "email_task_assignment", new_column_name="notify_task_assignment")
    op.alter_column("users", "email_project_added", new_column_name="notify_project_added")
    op.alter_column("users", "email_overdue_tasks", new_column_name="notify_overdue_tasks")
    op.alter_column("users", "email_mentions", new_column_name="notify_mentions")
