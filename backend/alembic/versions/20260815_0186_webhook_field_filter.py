"""Add the webhook column filter

Guild-content migration. ``fields`` narrows a subscription to the columns it
cares about: an update is delivered when the change's reported column names
intersect this set, so "tell me when a task's status or due date moves" stops
being "tell me about every task edit". NULL keeps the previous behaviour — any
change to a named event type.

Matching happens before an envelope is assembled, so a filtered-out change costs
a set intersection and no HTTP request.

Revision ID: 20260815_0186
Revises: 20260815_0185
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260815_0186"
down_revision = "20260815_0185"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.add_column(
        "webhook_subscriptions",
        sa.Column("fields", postgresql.ARRAY(sa.String(length=63)), nullable=True),
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.drop_column("webhook_subscriptions", "fields")
