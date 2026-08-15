"""Add subscription delivery state; drop workflow_id

Guild-content migration.

``failure_count`` / ``next_attempt_at`` are what let a cursor stay put after a
failed delivery without the poller retrying a dead target every pass: failures
accumulate a backoff, and the first 2xx resets both.

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

    op.add_column(
        "webhook_subscriptions",
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "webhook_subscriptions",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_column("webhook_subscriptions", "workflow_id")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.add_column(
        "webhook_subscriptions",
        sa.Column("workflow_id", sa.Integer(), nullable=True),
    )
    op.drop_column("webhook_subscriptions", "next_attempt_at")
    op.drop_column("webhook_subscriptions", "failure_count")

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
