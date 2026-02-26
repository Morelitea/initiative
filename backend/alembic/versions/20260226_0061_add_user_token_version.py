"""Add token_version column to users table for JWT invalidation.

Revision ID: 20260226_0061
Revises: 20260225_0060
Create Date: 2026-02-26
"""

from alembic import op
import sqlalchemy as sa

revision = "20260226_0061"
down_revision = "20260225_0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
