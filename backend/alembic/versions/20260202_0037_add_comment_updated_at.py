"""add comment updated_at

Revision ID: 20260202_0037
Revises: 20260201_0036
Create Date: 2026-02-02

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260202_0037"
down_revision = "20260201_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "comments",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("comments", "updated_at")
