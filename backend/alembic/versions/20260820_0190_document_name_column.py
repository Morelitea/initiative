"""Documents call their display column ``name`` like every other tool

Guild-content migration.

Every tool-level table (projects, queues, counter_groups, calendars,
dashboards) labels a row with a ``name`` column; ``documents`` alone said
``title``. One word for the same fact across the tools — ``tools_test.py``
now asserts the alignment, so a new tool that reintroduces a synonym fails CI.

Renamed in place (index included), so the data survives. ``title`` stays the
word for content *inside* a tool that genuinely is a title — tasks and
calendar events keep theirs.

Pre-v1 breaking rename — no compatibility shims, downgrade restores the old
name exactly.

Revision ID: 20260820_0190
Revises: 20260820_0189
Create Date: 2026-08-20
"""

from __future__ import annotations

from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260820_0190"
down_revision = "20260820_0189"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.alter_column("documents", "title", new_column_name="name")
    op.execute("ALTER INDEX ix_documents_title RENAME TO ix_documents_name")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.execute("ALTER INDEX ix_documents_name RENAME TO ix_documents_title")
    op.alter_column("documents", "name", new_column_name="title")
