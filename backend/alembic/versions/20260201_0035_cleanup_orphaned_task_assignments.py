"""Remove orphaned task assignments for users without write access

Revision ID: 20260201_0035
Revises: 20260131_0034
Create Date: 2026-02-01

This migration cleans up task assignments where the user no longer has write
access to the project (either no permission at all, or only read permission).

With pure DAC, users can only be assigned to tasks in projects where they have
write or owner permission. This migration removes any orphaned assignments that
may have existed before this constraint was enforced in application logic.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "20260201_0035"
down_revision = "20260131_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Delete task assignments where user lacks write access to the project
    # (either no permission exists, or permission level is 'read')
    op.execute("""
        DELETE FROM task_assignees ta
        WHERE NOT EXISTS (
            SELECT 1 FROM project_permissions pp
            JOIN tasks t ON t.project_id = pp.project_id
            WHERE t.id = ta.task_id
            AND pp.user_id = ta.user_id
            AND pp.level IN ('owner', 'write')
        )
    """)


def downgrade() -> None:
    # Cannot restore deleted assignments - they would need to be recreated
    # manually if needed. The downgrade is a no-op.
    pass
