"""an unproven address holds nothing

An address was unique across every row, proven or not. Adding one therefore
took it from everybody the moment it was typed, and the person who actually
holds the mailbox could no longer register with it or add it — with nothing to
undo that, because the row was never proven and never expires.

Uniqueness moves to the rows that have been proven. An unproven row is a claim
somebody is in the middle of making: two accounts may each have one for the
same address, the first to prove it takes it, and proving it clears the others.

The plain index replaces what the constraint was also providing: the lookup a
sign-in does.

Revision ID: 20260913_0264
Revises: 20260913_0263
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260913_0264"
down_revision = "20260913_0263"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_user_emails_email_hash", "user_emails", type_="unique")
    op.create_index("ix_user_emails_email_hash", "user_emails", ["email_hash"])
    op.create_index(
        "uq_user_emails_proven_hash",
        "user_emails",
        ["email_hash"],
        unique=True,
        postgresql_where=sa.text("verified_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_emails_proven_hash", table_name="user_emails")
    op.drop_index("ix_user_emails_email_hash", table_name="user_emails")
    op.create_unique_constraint(
        "uq_user_emails_email_hash", "user_emails", ["email_hash"]
    )
