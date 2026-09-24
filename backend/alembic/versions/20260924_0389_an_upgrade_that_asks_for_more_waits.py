"""an upgrade that asks for more waits for the seat

Two columns on ``guild_apps``, in every guild schema:

- ``pending_version``: a newer version of the listing that asks for more than
  the install holds (a scope it has not been granted, or a new surface inside
  initiatives). The auto-update sweep records it instead of applying it.
- ``declined_version``: the version the community's seat declined, which the
  sweep does not ask about again.

Both are NULL on every existing install.

Revision ID: 20260924_0389
Revises: 20260924_0388
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260924_0389"
down_revision = "20260924_0388"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.add_column(
        "guild_apps",
        sa.Column("pending_version", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "guild_apps",
        sa.Column("declined_version", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.drop_column("guild_apps", "declined_version")
    op.drop_column("guild_apps", "pending_version")
