"""The sign-in options gain the one the others hang off

``restrictions`` is the master: a guild without it configures no part of its
own sign-in, and the options already there mean nothing until it is granted.

The label only. Nothing uses it yet: the revision after this one grants it to
the guilds that already hold something, and it cannot do both, because a label
added inside a transaction cannot be used until that transaction has committed.
Alembic runs each revision in its own (``transaction_per_migration``), so two
revisions is what two transactions looks like here.

Revision ID: 20260917_0301
Revises: 20260917_0300
Create Date: 2026-09-17
"""

from alembic import op

revision = "20260917_0301"
down_revision = "20260917_0300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Adding a label is allowed inside the migration's transaction; using it in
    # the same one is not, and nothing here does.
    op.execute(
        "ALTER TYPE public.guild_auth_option ADD VALUE IF NOT EXISTS 'restrictions'"
    )


def downgrade() -> None:
    # Postgres cannot drop a label from an enum. Leaving it is inert: the
    # upgrade is idempotent, and the revision that follows takes the value back
    # out of every row that holds it before this one is reached.
    pass
