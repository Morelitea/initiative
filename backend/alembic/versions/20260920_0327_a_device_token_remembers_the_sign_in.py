"""a device token remembers the sign-in that minted it

A relay sign-in — the passkey one in the phone's system browser, and the SSO
mobile login before it — hands the app a device token rather than opening a
session, because the answer goes back through a redirect and a refresh token
does not belong in a URL. The app then trades that token for a session at
``POST /auth/device-token/exchange``, and that session recorded nothing about
how its owner proved who they were: somebody who had just signed in with a
passkey was refused by a community asking for one.

``user_tokens.amr`` carries the sign-in's own markers across the handoff, and
``amr_claimed_at`` records the exchange that took them. They are handed over
once and within a window of the mint: the first exchange is the rest of the
sign-in, and every exchange after it is the app resuming on a bearer string it
has been keeping.

Both are nullable/defaulted, so every token already issued reads as a sign-in
that recorded nothing — which is what those sessions already got.

Revision ID: 20260920_0327
Revises: 20260920_0326
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "20260920_0327"
down_revision = "20260920_0326"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_tokens",
        sa.Column(
            "amr",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "user_tokens",
        sa.Column("amr_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_tokens", "amr_claimed_at")
    op.drop_column("user_tokens", "amr")
