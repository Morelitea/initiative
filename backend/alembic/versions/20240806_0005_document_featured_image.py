"""Add featured image url to documents.

Revision ID: 20240806_0005
Revises: 20240806_0004
Create Date: 2024-08-06 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20240806_0005"
down_revision: Union[str, None] = "20240806_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("featured_image_url", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "featured_image_url")
