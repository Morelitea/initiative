"""every tool records its listing

Every tool now has a marketplace, and installing a listing imports a copy that
records the listing and version it came from. Dashboards already carried the
pair; this gives it to the other tools' tables.

Nullable and unindexed: NULL is everything made by hand, which is nearly every
row, and nothing reads these back by value yet (a dashboard does, and keeps the
index it has).

Revision ID: 20260923_0371
Revises: 20260923_0370
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260923_0371"
down_revision = "20260923_0370"
branch_labels = None
depends_on = None

_TABLES = (
    "calendars",
    "counter_groups",
    "documents",
    "galleries",
    "posts",
    "projects",
    "queues",
    "wikis",
)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("listing_uid", sa.String(length=14), nullable=True)
            )
            batch_op.add_column(
                sa.Column("listing_version", sa.String(length=32), nullable=True)
            )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column("listing_version")
            batch_op.drop_column("listing_uid")
