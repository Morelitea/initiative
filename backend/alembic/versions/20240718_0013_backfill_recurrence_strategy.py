"""Backfill recurrence strategy defaults.

Revision ID: 20240718_0013
Revises: 38864b4ddcc4
Create Date: 2024-07-18 03:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20240718_0013"
down_revision: Union[str, None] = "38864b4ddcc4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE tasks SET recurrence_strategy = 'fixed' WHERE recurrence_strategy IS NULL")


def downgrade() -> None:
    # Nothing to undo; leave values as-is.
    pass
