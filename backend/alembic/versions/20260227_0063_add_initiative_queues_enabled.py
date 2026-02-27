"""Add queues_enabled column to initiatives

Revision ID: 20260227_0063
Revises: 20260226_0062
Create Date: 2026-02-27
"""

from alembic import op
import sqlalchemy as sa

revision = "20260227_0063"
down_revision = "20260226_0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "initiatives",
        sa.Column("queues_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("initiatives", "queues_enabled")
