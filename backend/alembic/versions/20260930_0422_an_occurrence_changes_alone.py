"""an occurrence of a repeating event can change alone

An occurrence changed on its own (moved, renamed, given its own attendees) is an
ordinary event row in the series' calendar: ``series_id`` names the series,
``original_start`` the start it has there, and ``overridden_fields`` what it
changed. The key cascades, so an override goes with its series to the bin and
back. One override per occurrence.

An override takes write on the calendar, and answering an invitation takes
read, so an attendee's answer for one occurrence that has no row of its own is
kept in ``calendar_event_answers`` (event, person, occurrence). Its policies are
rendered at boot from the registry, like every guild table's.

Revision ID: 20260930_0422
Revises: 20260930_0421
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260930_0422"
down_revision = "20260930_0421"
branch_labels = None
depends_on = None


def _add() -> None:
    op.add_column(
        "calendar_events",
        sa.Column(
            "series_id",
            sa.Integer(),
            sa.ForeignKey("calendar_events.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "calendar_events",
        sa.Column("original_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "calendar_events",
        sa.Column(
            "overridden_fields",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.create_index("ix_calendar_events_series_id", "calendar_events", ["series_id"])
    op.create_unique_constraint(
        "uq_calendar_events_occurrence",
        "calendar_events",
        ["series_id", "original_start"],
    )
    op.create_table(
        "calendar_event_answers",
        sa.Column("calendar_event_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("original_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "rsvp_status",
            postgresql.ENUM(name="rsvp_status", schema="public", create_type=False),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["calendar_event_id"], ["calendar_events.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("calendar_event_id", "user_id", "original_start"),
    )
    op.create_index(
        "ix_calendar_event_answers_user_id", "calendar_event_answers", ["user_id"]
    )


def _drop() -> None:
    op.drop_table("calendar_event_answers")
    op.drop_constraint(
        "uq_calendar_events_occurrence", "calendar_events", type_="unique"
    )
    op.drop_index("ix_calendar_events_series_id", table_name="calendar_events")
    op.drop_column("calendar_events", "overridden_fields")
    op.drop_column("calendar_events", "original_start")
    op.drop_column("calendar_events", "series_id")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _add)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop)
