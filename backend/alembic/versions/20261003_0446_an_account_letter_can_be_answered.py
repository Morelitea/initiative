"""an account letter can be answered

An account letter is written once per address it goes to:
``email_outbox.recipient_encrypted`` holds that address, so a copy retries on
its own and can reach an address the account no longer holds.
``email_outbox.change`` names the account notice it is, which a link in the
letter answers. That link is a token of the new ``account_change`` purpose,
and ``user_tokens.change`` holds what it may do. ``auth_sessions.continues_since``
keeps when a sign-in began across a step-up, which starts a fresh chain.

The enum value is added alone: nothing in this revision uses it, so it needs
no transaction of its own. The downgrade leaves it, since Postgres cannot drop
an enum value, and drops the tokens that carry it.

Revision ID: 20261003_0446
Revises: 20261003_0445
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261003_0446"
down_revision = "20261003_0445"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE public.user_token_purpose ADD VALUE IF NOT EXISTS 'account_change'"
    )
    op.add_column(
        "email_outbox", sa.Column("recipient_encrypted", sa.Text(), nullable=True)
    )
    op.add_column(
        "email_outbox", sa.Column("change", postgresql.JSONB(), nullable=True)
    )
    op.add_column("user_tokens", sa.Column("change", postgresql.JSONB(), nullable=True))
    op.add_column(
        "auth_sessions",
        sa.Column("continues_since", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Row security binds this migration too, and nothing here has a request's
    # context to satisfy it, so it is lifted for the delete alone.
    op.execute("ALTER TABLE public.user_tokens NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute("DELETE FROM public.user_tokens WHERE change IS NOT NULL")
    finally:
        op.execute("ALTER TABLE public.user_tokens FORCE ROW LEVEL SECURITY")
    op.drop_column("auth_sessions", "continues_since")
    op.drop_column("user_tokens", "change")
    op.drop_column("email_outbox", "change")
    op.drop_column("email_outbox", "recipient_encrypted")
