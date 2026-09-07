"""add user_dm_settings.send_receipts where it is missing

``user_dm_settings`` was created by revision ``20260904_0223``, which shipped in
0.65.0. ``send_receipts`` was added to that same revision afterwards, in 0.66.0.
A database that ran 0.65.0 therefore has the table without the column, and
never sees the added line: the revision is already stamped. Reading DM settings
on such a database fails with ``column user_dm_settings.send_receipts does not
exist``.

This adds the column where it is absent and does nothing where 0.66.0 created
it, so both histories converge.

There is no downgrade: dropping a column the previous revision may or may not
have created cannot be expressed, and the column is what the app now expects.

Revision ID: 20260907_0234
Revises: 20260907_0233
Create Date: 2026-09-07
"""

from alembic import op

revision = "20260907_0234"
down_revision = "20260907_0233"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.user_dm_settings "
        "ADD COLUMN IF NOT EXISTS send_receipts boolean NOT NULL DEFAULT true"
    )


def downgrade() -> None:
    pass
