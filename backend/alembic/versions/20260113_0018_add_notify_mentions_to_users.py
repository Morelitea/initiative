"""Add notify_mentions field to users table.

Revision ID: 20260113_0018
Revises: 20251219_2041
Create Date: 2026-01-13 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260113_0018"
down_revision: Union[str, None] = "20251219_2041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("notify_mentions", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("users", "notify_mentions")
