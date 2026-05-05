"""Create auto_delegation_jti_blocklist for one-shot delegation tokens.

Delegation JWTs minted by initiative-auto carry a ``jti`` claim. The
auth dep records every successfully-redeemed jti here and refuses any
second presentation, so a leaked or sniffed token can be used at most
once even though the JWT itself is valid for 15 minutes.

``expires_at`` is set to the JWT's ``exp`` so a periodic cleanup (or a
lazy delete on insert) can keep the table tiny — entries past their
JWT exp are useless.

Revision ID: 20260501_0081
Revises: 20260501_0080
Create Date: 2026-05-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260501_0081"
down_revision: Union[str, None] = "20260501_0080"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auto_delegation_jti_blocklist",
        sa.Column("jti", sa.String(length=64), primary_key=True),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Cleanup index — periodic ``DELETE WHERE expires_at < now()``.
    op.create_index(
        "ix_auto_delegation_jti_blocklist_expires_at",
        "auto_delegation_jti_blocklist",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auto_delegation_jti_blocklist_expires_at",
        table_name="auto_delegation_jti_blocklist",
    )
    op.drop_table("auto_delegation_jti_blocklist")
