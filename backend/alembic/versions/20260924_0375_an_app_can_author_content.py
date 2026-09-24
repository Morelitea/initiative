"""an app can author content

An app acting as its community writes with no person in context, so the
``fn_set_created_by`` trigger leaves ``created_by`` NULL, as it does for a
background job. The tables an app's scopes can write drop their NOT NULL to the
mixin's floor. The owner grant, not this column, says which install made a row.

Tables no scope writes keep NOT NULL: file and picture versions, pictures,
reactions, uploads, export and import jobs, and apps.

Revision ID: 20260924_0375
Revises: 20260924_0374
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260924_0375"
down_revision = "20260924_0374"
branch_labels = None
depends_on = None


_TABLES = (
    "calendars",
    "calendar_events",
    "comments",
    "counter_groups",
    "dashboards",
    "documents",
    "galleries",
    "posts",
    "queues",
    "wikis",
    "wiki_pages",
    "webhook_subscriptions",
)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    for table in _TABLES:
        op.alter_column(table, "created_by", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    for table in _TABLES:
        op.alter_column(table, "created_by", existing_type=sa.Integer(), nullable=False)
