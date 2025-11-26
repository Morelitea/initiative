"""Add members_can_write flag to projects.

Revision ID: 20240802_0015
Revises: 20240801_0014
Create Date: 2024-08-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20240802_0015"
down_revision: Union[str, None] = "20240801_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("members_can_write", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.alter_column("projects", "members_can_write", server_default=None)


def downgrade() -> None:
    op.drop_column("projects", "members_can_write")
