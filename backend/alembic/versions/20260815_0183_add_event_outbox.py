"""Add the change-capture outbox and per-subscription cursor

Guild-content migration. ``event_outbox`` is the append-only log the capture
trigger writes one row to per changed content row: identifiers, the action, and
the names of the columns that changed — never a value. Consumers read current
state back through the REST API, where the six gates apply to the read.

``initiative_id`` is NOT NULL: the trigger resolves it from the same
``INITIATIVE_PATHS`` declaration that renders each table's RLS policies, and
skips emitting when it cannot (an orphaned child row during a parent cascade —
whose parent already emitted its own ``deleted``). RLS for this table comes from
that registry at provisioning time, not from this migration.

``webhook_subscriptions.cursor_event_id`` is each subscription's position in the
log. Delivery state lives there rather than in per-(event, subscription) rows,
so one log row serves any number of subscribers and retention is an age sweep.

Revision ID: 20260815_0183
Revises: 20260815_0182
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260815_0183"
down_revision = "20260815_0182"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.create_table(
        "event_outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("txn_id", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(length=63), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column(
            "changed",
            postgresql.ARRAY(sa.String(length=63)),
            nullable=False,
            server_default="{}",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "action IN ('created', 'updated', 'deleted')",
            name="ck_event_outbox_action",
        ),
    )
    with op.batch_alter_table("event_outbox", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_event_outbox_txn_id"), ["txn_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_event_outbox_occurred_at"), ["occurred_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_event_outbox_initiative_id"),
            ["initiative_id"],
            unique=False,
        )

    op.add_column(
        "webhook_subscriptions",
        sa.Column(
            "cursor_event_id",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.drop_column("webhook_subscriptions", "cursor_event_id")
    with op.batch_alter_table("event_outbox", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_event_outbox_initiative_id"))
        batch_op.drop_index(batch_op.f("ix_event_outbox_occurred_at"))
        batch_op.drop_index(batch_op.f("ix_event_outbox_txn_id"))
    op.drop_table("event_outbox")
