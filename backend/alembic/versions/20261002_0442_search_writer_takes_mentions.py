"""search writer takes mentions

``public.search_entry_write`` takes the people an entry's body mentions as an
eleventh argument. A start renders it from the registry, and ``CREATE OR
REPLACE`` with a new argument list makes a second function rather than
replacing the first, so the ten-argument one is dropped here. A fresh install
never had it.

Revision ID: 20261002_0442
Revises: 20261002_0441
Create Date: 2026-10-02
"""

from alembic import op

revision = "20261002_0442"
down_revision = "20261002_0441"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS public.search_entry_write("
        "text, text, integer, integer, text, integer, text, text, boolean, boolean)"
    )


def downgrade() -> None:
    # A start on the previous release renders the ten-argument writer again.
    pass
