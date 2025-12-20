"""Rename admin_api_keys table to user_api_keys.

Revision ID: 20251219_2041
Revises: 20251215_0017
Create Date: 2025-12-19 20:41:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20251219_2041"
down_revision: Union[str, None] = "20251215_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename table from admin_api_keys to user_api_keys
    op.rename_table("admin_api_keys", "user_api_keys")


def downgrade() -> None:
    # Rollback: rename table back to admin_api_keys
    op.rename_table("user_api_keys", "admin_api_keys")
