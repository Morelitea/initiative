"""Add device_auth tokens for mobile app authentication

Revision ID: 20260115_0019
Revises: 8bab3c8344af
Create Date: 2026-01-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260115_0019"
down_revision: Union[str, None] = "8bab3c8344af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add device_auth to the user_token_purpose enum
    op.execute("ALTER TYPE user_token_purpose ADD VALUE IF NOT EXISTS 'device_auth'")

    # Add device_name column to user_tokens table
    op.add_column(
        "user_tokens",
        sa.Column("device_name", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    # Remove device_name column
    op.drop_column("user_tokens", "device_name")

    # Note: PostgreSQL doesn't support removing enum values easily.
    # The device_auth value will remain in the enum but won't be used.
