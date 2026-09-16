"""an account is reached by its addresses

``users`` carried the one address an account was created with — a hash to look
it up by, the ciphertext to write to, and whether it had been confirmed.
``user_emails`` has held every address an account has since 0261, including
that one, and everything that reads or writes an address now reads it there:
the sign-in lookup, account and notification mail, secret-key rotation,
erasure, and the account's own record.

The three columns go. Nothing consults them, and a value in two places is a
value that can disagree.

One-way. ``users.email_hash`` was NOT NULL and unique across the whole
table, and ``user_emails`` allows an account to hold no address at all, so
there is no rebuilding the column for every row.

Revision ID: 20260915_0273
Revises: 20260915_0272
Create Date: 2026-09-15
"""

from __future__ import annotations

from alembic import op

revision = "20260915_0273"
down_revision = "20260915_0272"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_users_email_hash", "users", type_="unique")
    op.drop_column("users", "email_hash")
    op.drop_column("users", "email_encrypted")
    op.drop_column("users", "email_verified")


def downgrade() -> None:
    raise NotImplementedError(
        "users.email_hash was NOT NULL and unique across every account. "
        "user_emails holds an address per account and allows an account to "
        "hold none, so the column cannot be rebuilt for every row. Roll "
        "forward, or restore from a backup taken before this revision."
    )
