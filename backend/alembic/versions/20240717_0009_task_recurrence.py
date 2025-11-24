"""Add recurrence data to tasks.

Revision ID: 20240717_0009
Revises: 20240717_0008
Create Date: 2024-07-17 01:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20240717_0009"
down_revision: Union[str, None] = "20240717_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("recurrence", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "recurrence")
