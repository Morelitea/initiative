"""a verification names the address

An account had one address, so a verification token only had to name the
account. With several, the token names the one it proves, and confirming it
confirms that address alone.

``user_email_id`` is NULL for the tokens that predate this and for the
account-level flows that keep no address of their own (a password reset names
the account, not an address).

CASCADE: the token proves one address, so it goes with it.

Revision ID: 20260913_0263
Revises: 20260913_0262
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260913_0263"
down_revision = "20260913_0262"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_tokens", sa.Column("user_email_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_user_tokens_user_email_id",
        "user_tokens",
        "user_emails",
        ["user_email_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_user_tokens_user_email_id", "user_tokens", type_="foreignkey"
    )
    op.drop_column("user_tokens", "user_email_id")
