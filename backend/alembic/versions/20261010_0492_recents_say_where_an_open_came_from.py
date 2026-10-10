"""recents say where an open came from

``recent_views.source``, in every guild schema: where the person's latest open
came from, ``direct`` or ``search``. Its CHECK, and the wider one on
``entity_type`` that admits the kinds inside a tool, are rendered from the
model at boot.

The downgrade drops ``source``, and its CHECK with it.

Revision ID: 20261010_0492
Revises: 20261010_0491
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261010_0492"
down_revision = "20261010_0491"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.add_column(
        "recent_views",
        sa.Column("source", sa.Text(), nullable=False, server_default="direct"),
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.drop_column("recent_views", "source")
