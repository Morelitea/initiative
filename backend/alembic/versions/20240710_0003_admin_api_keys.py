"""Add admin API keys table.

Revision ID: 20240710_0003
Revises: 20240709_0002
Create Date: 2024-07-10 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20240710_0003"
down_revision: Union[str, None] = "20240709_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_admin_api_keys_token_prefix"), "admin_api_keys", ["token_prefix"], unique=False)
    op.create_index(op.f("ix_admin_api_keys_user_id"), "admin_api_keys", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_api_keys_user_id"), table_name="admin_api_keys")
    op.drop_index(op.f("ix_admin_api_keys_token_prefix"), table_name="admin_api_keys")
    op.drop_table("admin_api_keys")
