"""Add recurrence strategy to tasks.

Revision ID: 20240718_0012
Revises: 20240717_0011
Create Date: 2024-07-18 02:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20240718_0012"
down_revision: Union[str, None] = "20240717_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("recurrence_strategy", sa.String(length=20), nullable=False, server_default="fixed"),
    )
    op.alter_column("tasks", "recurrence_strategy", server_default=None)


def downgrade() -> None:
    op.drop_column("tasks", "recurrence_strategy")
