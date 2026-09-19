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

Revision ID: 20260915_0274
Revises: 20260915_0273
Create Date: 2026-09-15
"""

from __future__ import annotations

from alembic import op

revision = "20260915_0274"
down_revision = "20260915_0273"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``IF EXISTS`` throughout: what this revision asserts is the end state, and
    # a database that already reached it — one that ran this revision under an
    # earlier number while it was being written — arrives here with nothing
    # left to drop. A removal that insisted on finding them would stop such a
    # database on a difference that does not matter.
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_users_email_hash")
    for column in ("email_hash", "email_encrypted", "email_verified"):
        op.execute(f"ALTER TABLE users DROP COLUMN IF EXISTS {column}")


def downgrade() -> None:
    raise NotImplementedError(
        "users.email_hash was NOT NULL and unique across every account. "
        "user_emails holds an address per account and allows an account to "
        "hold none, so the column cannot be rebuilt for every row. Roll "
        "forward, or restore from a backup taken before this revision."
    )
