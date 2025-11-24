"""Add initiative color metadata.

Revision ID: 20240717_0007
Revises: 20240716_0006
Create Date: 2024-07-17 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20240717_0007"
down_revision: Union[str, None] = "20240716_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "initiatives",
        sa.Column("color", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("initiatives", "color")
