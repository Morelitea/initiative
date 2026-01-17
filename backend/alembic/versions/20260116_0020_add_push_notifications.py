"""Add push_tokens table for mobile push notifications

Revision ID: 20260116_0020
Revises: 20260115_0019
Create Date: 2026-01-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260116_0020"
down_revision: Union[str, None] = "20260115_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create push_tokens table
    op.create_table(
        "push_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("device_token_id", sa.Integer(), nullable=True),
        sa.Column("push_token", sa.String(512), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["device_token_id"], ["user_tokens.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes
    op.create_index("ix_push_tokens_user_id", "push_tokens", ["user_id"])
    op.create_index("ix_push_tokens_push_token", "push_tokens", ["push_token"])
    op.create_index(
        "ix_push_tokens_user_device_token",
        "push_tokens",
        ["user_id", "push_token"],
        unique=True,
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_push_tokens_user_device_token", "push_tokens")
    op.drop_index("ix_push_tokens_push_token", "push_tokens")
    op.drop_index("ix_push_tokens_user_id", "push_tokens")

    # Drop table
    op.drop_table("push_tokens")
