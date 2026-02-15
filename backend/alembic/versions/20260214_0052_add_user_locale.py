"""add user locale column

Revision ID: 20260214_0052
Revises: 20260212_0051
Create Date: 2026-02-14

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260214_0052"
down_revision = "20260212_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("locale", sa.String(10), nullable=False, server_default="en"),
    )


def downgrade() -> None:
    op.drop_column("users", "locale")
