"""Add week_starts_on preference to users.

Revision ID: 20240811_0012
Revises: 20240810_0011
Create Date: 2024-08-11 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20240811_0012"
down_revision: Union[str, None] = "20240810_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("week_starts_on", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("users", "week_starts_on")

