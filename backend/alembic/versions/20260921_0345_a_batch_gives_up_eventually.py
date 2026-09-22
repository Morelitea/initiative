"""a batch gives up eventually

Guild-content migration.

``webhook_deliveries.dead_lettered_at`` is the terminal state a refused batch
reaches once it has exhausted the poller's backoff schedule. Before this, a
refused batch retried at the schedule's final interval forever, and every
later transaction for that subscription queued up behind it — a permanently
unreachable target meant the subscription never delivered anything again.

Revision ID: 20260921_0345
Revises: 20260921_0344
Create Date: 2026-09-21
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260921_0345"
down_revision = "20260921_0344"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("webhook_deliveries", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            batch_op.f("ix_webhook_deliveries_dead_lettered_at"),
            ["dead_lettered_at"],
            unique=False,
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("webhook_deliveries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_webhook_deliveries_dead_lettered_at"))
        batch_op.drop_column("dead_lettered_at")
