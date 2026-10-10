"""a project opens on its default view

``projects.default_view_mode`` goes: the view a project opens on is the one of
its views marked default (``tool_views``, 20261009_0478), and nothing reads the
column any more.

The downgrade puts the column back, filled from each project's default view
where the project stores views: that view's layout, ``board`` spelled
``kanban``. A project with no stored views, or whose default view has a layout
the column never named, gets none.

Revision ID: 20261009_0479
Revises: 20261009_0478
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261009_0479"
down_revision = "20261009_0478"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.drop_column("projects", "default_view_mode")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("default_view_mode", sa.String(length=16), nullable=True),
    )
    bind = op.get_bind()
    # The projects are written and the views read with their row security
    # lifted, and the projects' request triggers (the freeze, change capture,
    # search) held. ``guild_template`` carries no row security, so only what
    # was set is put back.
    forced = [
        table
        for table in ("projects", "tool_views")
        if bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    ]
    for table in forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE projects DISABLE TRIGGER USER")
    try:
        op.execute(
            "UPDATE projects p SET default_view_mode = CASE v.layout"
            " WHEN 'board' THEN 'kanban' ELSE v.layout END"
            " FROM (SELECT tool_id, definition #>> '{layout,type}' AS layout"
            " FROM tool_views WHERE tool = 'project' AND kind = 'view'"
            " AND is_default) v"
            " WHERE v.tool_id = p.id AND v.layout IN ('table', 'board', 'calendar')"
        )
    finally:
        op.execute("ALTER TABLE projects ENABLE TRIGGER USER")
        for table in forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
