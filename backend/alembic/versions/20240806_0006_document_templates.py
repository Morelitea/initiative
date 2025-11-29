"""Add template flag to documents.

Revision ID: 20240806_0006
Revises: 20240806_0005
Create Date: 2024-08-06 00:00:00.000001
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20240806_0006"
down_revision: Union[str, None] = "20240806_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("documents", "is_template", server_default=None)


def downgrade() -> None:
    op.drop_column("documents", "is_template")
