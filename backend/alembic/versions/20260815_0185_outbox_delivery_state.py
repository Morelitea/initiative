"""Add the delivery ledger; drop the cursor and workflow_id

Guild-content migration.

``webhook_deliveries`` records what each subscription has been told about, one
transaction at a time, replacing ``cursor_event_id``. A cursor cannot be correct
here: outbox ids are assigned at insert and published at commit, so a
transaction still in flight can put a row beneath a watermark chosen while that
row was invisible, and the event under it is never read again. A row per
(subscription, transaction) has nothing for a late row to be beneath, and its
primary key doubles as the claim two replicas race on.

Retry state moves onto that row, so a refusal backs off the batch that was
refused rather than the whole subscription.

``workflow_id`` goes. It was documented as opaque to us, with its source of
truth in the consumer's own database — foreign bookkeeping held in our column,
our request/response schemas, our delivery envelope, and our delegation-token
claim validation. A consumer routes on ``subscription_id``, which the envelope
carries, and keeps its own map.

Revision ID: 20260815_0185
Revises: 20260815_0184
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260815_0185"
down_revision = "20260815_0184"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    # The capture trigger fires while a row is being deleted, including when
    # that deletion is the cascade from removing the initiative or user the
    # event names — so the log's own insert would fail the delete it is
    # reporting. Both references become weak (plain ints): the log outlives what
    # it describes, retention sweeps orphans, and RLS still resolves
    # initiative_id through initiative_access.
    op.drop_constraint(
        "event_outbox_initiative_id_fkey", "event_outbox", type_="foreignkey"
    )
    op.drop_constraint(
        "event_outbox_actor_user_id_fkey", "event_outbox", type_="foreignkey"
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("txn_id", sa.BigInteger(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["webhook_subscriptions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("subscription_id", "txn_id"),
    )
    with op.batch_alter_table("webhook_deliveries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_webhook_deliveries_delivered_at"),
            ["delivered_at"],
            unique=False,
        )

    op.drop_column("webhook_subscriptions", "cursor_event_id")
    op.drop_column("webhook_subscriptions", "workflow_id")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.add_column(
        "webhook_subscriptions",
        sa.Column("workflow_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "webhook_subscriptions",
        sa.Column(
            "cursor_event_id", sa.BigInteger(), nullable=False, server_default="0"
        ),
    )
    with op.batch_alter_table("webhook_deliveries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_webhook_deliveries_delivered_at"))
    op.drop_table("webhook_deliveries")

    op.create_foreign_key(
        "event_outbox_actor_user_id_fkey",
        "event_outbox",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "event_outbox_initiative_id_fkey",
        "event_outbox",
        "initiatives",
        ["initiative_id"],
        ["id"],
        ondelete="CASCADE",
    )
