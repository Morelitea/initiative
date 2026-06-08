"""Calendar event notification preferences + reminder dispatch ledger.

Adds per-user notification preferences for calendar events (lifecycle
notifications and scheduled reminders) plus a configurable reminder lead time,
and creates the ``event_reminder_dispatches`` dedup ledger used by the
background reminder dispatcher.

Revision ID: 20260607_0097
Revises: 20260531_0096
Create Date: 2026-06-07
"""

from alembic import op
import sqlalchemy as sa

revision = "20260607_0097"
down_revision = "20260531_0096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_events", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "users",
        sa.Column("push_events", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_event_reminders", sa.Boolean(), nullable=False, server_default="true"
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "push_event_reminders", sa.Boolean(), nullable=False, server_default="true"
        ),
    )
    # NULL = reminders off; default lead time is 15 minutes.
    op.add_column(
        "users",
        sa.Column(
            "event_reminder_minutes_before",
            sa.Integer(),
            nullable=True,
            server_default="15",
        ),
    )

    op.create_table(
        "event_reminder_dispatches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"], ["calendar_events.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            "user_id",
            "event_start_at",
            name="uq_event_reminder_dispatch",
        ),
    )
    op.create_index(
        op.f("ix_event_reminder_dispatches_event_id"),
        "event_reminder_dispatches",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_event_reminder_dispatches_user_id"),
        "event_reminder_dispatches",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_event_reminder_dispatches_user_id"),
        table_name="event_reminder_dispatches",
    )
    op.drop_index(
        op.f("ix_event_reminder_dispatches_event_id"),
        table_name="event_reminder_dispatches",
    )
    op.drop_table("event_reminder_dispatches")

    op.drop_column("users", "event_reminder_minutes_before")
    op.drop_column("users", "push_event_reminders")
    op.drop_column("users", "email_event_reminders")
    op.drop_column("users", "push_events")
    op.drop_column("users", "email_events")
