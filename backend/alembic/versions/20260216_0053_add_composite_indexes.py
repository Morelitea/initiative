"""add composite indexes for heavily filtered columns

Revision ID: 20260216_0053
Revises: 20260214_0052
Create Date: 2026-02-16

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260216_0053"
down_revision = "20260214_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite index for task list queries (project_id + is_archived)
    op.create_index(
        "idx_tasks_project_archived",
        "tasks",
        ["project_id", "is_archived"],
        unique=False,
    )

    # Partial index for overdue task queries (due_date + task_status_id)
    op.create_index(
        "idx_tasks_due_date_status",
        "tasks",
        ["due_date", "task_status_id"],
        unique=False,
        postgresql_where=sa.text("due_date IS NOT NULL"),
    )

    # Composite index for guild membership lookups - checked on every request
    op.create_index(
        "idx_guild_memberships_user_guild",
        "guild_memberships",
        ["user_id", "guild_id"],
        unique=False,
    )

    # Index for task sorting by updated_at
    op.create_index(
        "idx_tasks_updated_at",
        "tasks",
        ["updated_at"],
        unique=False,
    )

    # Index for document sorting by updated_at
    op.create_index(
        "idx_documents_updated_at",
        "documents",
        ["updated_at"],
        unique=False,
    )

    # Partial index for notification digest processing
    op.create_index(
        "idx_task_assignment_digest_items_unprocessed",
        "task_assignment_digest_items",
        ["processed_at"],
        unique=False,
        postgresql_where=sa.text("processed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_task_assignment_digest_items_unprocessed", table_name="task_assignment_digest_items")
    op.drop_index("idx_documents_updated_at", table_name="documents")
    op.drop_index("idx_tasks_updated_at", table_name="tasks")
    op.drop_index("idx_guild_memberships_user_guild", table_name="guild_memberships")
    op.drop_index("idx_tasks_due_date_status", table_name="tasks")
    op.drop_index("idx_tasks_project_archived", table_name="tasks")
