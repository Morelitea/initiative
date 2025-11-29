"""Add comments table.

Revision ID: 20240808_0009
Revises: 20240807_0008
Create Date: 2024-08-08 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20240808_0009"
down_revision: Union[str, None] = "20240807_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("parent_comment_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_comment_id"], ["comments.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(task_id IS NULL) <> (document_id IS NULL)",
            name="ck_comments_task_or_document",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_comments_author_id", "comments", ["author_id"])
    op.create_index("ix_comments_task_id", "comments", ["task_id"])
    op.create_index("ix_comments_document_id", "comments", ["document_id"])
    op.create_index("ix_comments_parent_comment_id", "comments", ["parent_comment_id"])


def downgrade() -> None:
    op.drop_index("ix_comments_parent_comment_id", table_name="comments")
    op.drop_index("ix_comments_document_id", table_name="comments")
    op.drop_index("ix_comments_task_id", table_name="comments")
    op.drop_index("ix_comments_author_id", table_name="comments")
    op.drop_table("comments")
