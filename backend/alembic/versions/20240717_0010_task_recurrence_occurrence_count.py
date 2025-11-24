"""Track recurrence completion counts.

Revision ID: 20240717_0010
Revises: 20240717_0009
Create Date: 2024-07-17 02:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20240717_0010"
down_revision: Union[str, None] = "20240717_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "recurrence_occurrence_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("tasks", "recurrence_occurrence_count", server_default=None)


def downgrade() -> None:
    op.drop_column("tasks", "recurrence_occurrence_count")
