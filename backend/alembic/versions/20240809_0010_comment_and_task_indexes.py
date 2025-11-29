"""Add comment and task indexes.

Revision ID: 20240809_0010
Revises: 20240808_0009
Create Date: 2024-08-09 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20240809_0010"
down_revision: Union[str, None] = "20240808_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_comments_created_at", "comments", ["created_at"])
    op.create_index("ix_tasks_project_id_id", "tasks", ["project_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_project_id_id", table_name="tasks")
    op.drop_index("ix_comments_created_at", table_name="comments")

