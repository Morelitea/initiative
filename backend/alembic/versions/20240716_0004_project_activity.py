"""Track project favorites and recent views.

Revision ID: 20240716_0004
Revises: 20240710_0003
Create Date: 2024-07-16 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20240716_0004"
down_revision: Union[str, None] = "20240710_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_favorites",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_id"),
    )
    op.create_index(op.f("ix_project_favorites_user_id"), "project_favorites", ["user_id"], unique=False)
    op.create_index(op.f("ix_project_favorites_project_id"), "project_favorites", ["project_id"], unique=False)

    op.create_table(
        "recent_project_views",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_id"),
    )
    op.create_index(op.f("ix_recent_project_views_user_id"), "recent_project_views", ["user_id"], unique=False)
    op.create_index(op.f("ix_recent_project_views_project_id"), "recent_project_views", ["project_id"], unique=False)
    op.create_index(
        op.f("ix_recent_project_views_last_viewed_at"),
        "recent_project_views",
        ["last_viewed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_recent_project_views_last_viewed_at"), table_name="recent_project_views")
    op.drop_index(op.f("ix_recent_project_views_project_id"), table_name="recent_project_views")
    op.drop_index(op.f("ix_recent_project_views_user_id"), table_name="recent_project_views")
    op.drop_table("recent_project_views")

    op.drop_index(op.f("ix_project_favorites_project_id"), table_name="project_favorites")
    op.drop_index(op.f("ix_project_favorites_user_id"), table_name="project_favorites")
    op.drop_table("project_favorites")
