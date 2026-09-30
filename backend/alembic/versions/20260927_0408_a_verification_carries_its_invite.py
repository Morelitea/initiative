"""a verification carries its invite

Somebody signing up with an invite bound to their address has not proved the
address yet, so the invite cannot be redeemed with the account. The
verification token remembers it, and confirming the address joins the guild.

``invite_id`` is NULL for every other token.

SET NULL: an invite withdrawn before the address is confirmed leaves the token
proving the address and joining nothing.

Revision ID: 20260927_0408
Revises: 20260927_0407
Create Date: 2026-09-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260927_0408"
down_revision = "20260927_0407"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_tokens", sa.Column("invite_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_user_tokens_invite_id",
        "user_tokens",
        "guild_invites",
        ["invite_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_user_tokens_invite_id", "user_tokens", type_="foreignkey")
    op.drop_column("user_tokens", "invite_id")
