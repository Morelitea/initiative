"""Drop legacy team name unique constraint after guild rollout.

Revision ID: 20240804_0002
Revises: 20240803_0001
Create Date: 2024-08-04 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20240804_0002"
down_revision: Union[str, None] = "20240803_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Older databases still have the pre-rename unique constraint on initiative names,
    # which now conflicts with guild-scoped initiatives. Drop both possible names.
    op.execute("ALTER TABLE initiatives DROP CONSTRAINT IF EXISTS teams_name_key;")
    op.execute("ALTER TABLE initiatives DROP CONSTRAINT IF EXISTS initiatives_name_key;")


def downgrade() -> None:
    # Recreate the legacy global unique constraint on initiative names.
    op.execute("ALTER TABLE initiatives ADD CONSTRAINT initiatives_name_key UNIQUE (name);")
