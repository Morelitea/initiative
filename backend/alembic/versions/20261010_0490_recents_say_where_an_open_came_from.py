"""recents say where an open came from

``recent_views.source``, in every guild schema: where the person's latest open
came from, ``direct`` or ``search``. Its CHECK, and the wider one on
``entity_type`` that admits the kinds inside a tool, are rendered from the
model at boot.

The downgrade deletes the rows of the kinds inside a tool, which the earlier
render does not admit, and drops ``source``.

Revision ID: 20261010_0490
Revises: 20261010_0489
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261010_0490"
down_revision = "20261010_0489"
branch_labels = None
depends_on = None

_INSIDE_A_TOOL = (
    "task",
    "queue_item",
    "calendar_event",
    "counter",
    "gallery_image",
    "wiki_page",
)


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
    op.execute("ALTER TABLE recent_views NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            sa.text(
                "DELETE FROM recent_views WHERE entity_type = ANY(:kinds)"
            ).bindparams(kinds=list(_INSIDE_A_TOOL))
        )
    finally:
        op.execute("ALTER TABLE recent_views FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER TABLE recent_views DROP CONSTRAINT IF EXISTS ck_recent_views_source"
    )
    op.drop_column("recent_views", "source")
