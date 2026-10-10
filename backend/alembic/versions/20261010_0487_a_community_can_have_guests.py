"""a community can have guests

``guild_role`` gains ``guest``: an outside person in a community for a set
time. Only the value is added here; Postgres will not let a new enum value be
used in the transaction that adds it, so everything that names it is in the
next revision.

Revision ID: 20261010_0487
Revises: 20261010_0486
Create Date: 2026-10-10
"""

from __future__ import annotations

from alembic import op

revision = "20261010_0487"
down_revision = "20261010_0486"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE public.guild_role ADD VALUE IF NOT EXISTS 'guest'")


def downgrade() -> None:
    # Postgres cannot drop a label from an enum. The next revision's downgrade
    # removes every guest row, so the label is left inert.
    pass
