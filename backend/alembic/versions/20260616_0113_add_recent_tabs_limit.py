"""Add recent_tabs_limit column to users table.

Per-user cap on how many recently-opened items the header tabs bar keeps and
shows, across all entity types and guilds. Default 20 preserves the historic
fixed behavior.

Revision ID: 20260616_0113
Revises: 20260616_0112
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa

revision = "20260616_0113"
down_revision = "20260616_0112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "recent_tabs_limit",
            sa.Integer(),
            nullable=False,
            server_default="20",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "recent_tabs_limit")
