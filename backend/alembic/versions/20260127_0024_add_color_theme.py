"""Add color_theme column to users table.

Revision ID: 20260127_0024
Revises: 20260124_0023
Create Date: 2026-01-27

Adds user preference for color theme selection.
The default theme is "kobold" (the classic Initiative indigo theme).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260127_0024"
down_revision: Union[str, None] = "20260124_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("color_theme", sa.String(50), nullable=False, server_default="kobold")
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("color_theme")
