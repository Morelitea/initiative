"""Add user UI preference flags.

Revision ID: 20240716_0005
Revises: 20240716_0004
Create Date: 2024-07-16 00:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20240716_0005"
down_revision: Union[str, None] = "20240716_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("show_project_sidebar", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "users",
        sa.Column("show_project_tabs", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("users", "show_project_tabs")
    op.drop_column("users", "show_project_sidebar")
