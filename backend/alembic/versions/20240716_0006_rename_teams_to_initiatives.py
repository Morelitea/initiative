"""Rename teams to initiatives.

Revision ID: 20240716_0006
Revises: 20240716_0005
Create Date: 2024-07-16 01:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20240716_0006"
down_revision: Union[str, None] = "20240716_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE team_members RENAME TO initiative_members')
    op.execute('ALTER TABLE initiative_members RENAME COLUMN team_id TO initiative_id')
    op.execute('ALTER TABLE projects RENAME COLUMN team_id TO initiative_id')
    op.execute('ALTER TABLE teams RENAME TO initiatives')
    op.execute('ALTER INDEX IF EXISTS ix_teams_name RENAME TO ix_initiatives_name')


def downgrade() -> None:
    op.execute('ALTER INDEX IF EXISTS ix_initiatives_name RENAME TO ix_teams_name')
    op.execute('ALTER TABLE initiatives RENAME TO teams')
    op.execute('ALTER TABLE projects RENAME COLUMN initiative_id TO team_id')
    op.execute('ALTER TABLE initiative_members RENAME COLUMN initiative_id TO team_id')
    op.execute('ALTER TABLE initiative_members RENAME TO team_members')
