"""Add document permissions table.

Revision ID: 20240806_0007
Revises: 20240806_0006
Create Date: 2024-08-06 00:00:02.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20240806_0007"
down_revision: Union[str, None] = "20240806_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ENUM_NAME = "document_permission_level"
ENUM_VALUES = ("read", "write")


def upgrade() -> None:
    bind = op.get_bind()
    enum_type = postgresql.ENUM(*ENUM_VALUES, name=ENUM_NAME)
    enum_type.create(bind, checkfirst=True)

    document_permission_enum = postgresql.ENUM(
        *ENUM_VALUES, name=ENUM_NAME, create_type=False
    )

    op.create_table(
        "document_permissions",
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "level",
            document_permission_enum,
            nullable=False,
            server_default="write",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id", "user_id"),
    )
    op.alter_column("document_permissions", "level", server_default=None)


def downgrade() -> None:
    op.drop_table("document_permissions")
    enum_type = postgresql.ENUM(*ENUM_VALUES, name=ENUM_NAME)
    enum_type.drop(op.get_bind(), checkfirst=True)
