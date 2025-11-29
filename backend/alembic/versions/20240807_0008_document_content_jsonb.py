"""Convert document content to jsonb.

Revision ID: 20240807_0008
Revises: 20240806_0007
Create Date: 2024-08-07 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20240807_0008"
down_revision: Union[str, None] = "20240806_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "documents",
        "content",
        type_=sa.dialects.postgresql.JSONB(),
        postgresql_using="content::jsonb",
        existing_nullable=False,
    )
    op.alter_column(
        "documents",
        "content",
        server_default=sa.text("'{}'::jsonb"),
    )


def downgrade() -> None:
    op.alter_column(
        "documents",
        "content",
        type_=sa.dialects.postgresql.JSON(),
        postgresql_using="content::json",
        existing_nullable=False,
    )
    op.alter_column(
        "documents",
        "content",
        server_default=sa.text("'{}'::json"),
    )
