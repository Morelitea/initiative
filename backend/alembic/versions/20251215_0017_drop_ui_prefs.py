"""Drop unused user UI preference columns.

Revision ID: 20251215_0017
Revises: 20240821_0016
Create Date: 2025-12-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20251215_0017"
down_revision: Union[str, None] = "20240821_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("users", "show_project_tabs")
    op.drop_column("users", "show_project_sidebar")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("show_project_sidebar", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "users",
        sa.Column("show_project_tabs", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
