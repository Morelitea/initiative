"""an event may close its RSVP

``calendar_events.rsvp_open`` says whether anyone who can read the event may
answer it and so join it (the default), or only the people already on its
list. Every event that predates it stays open.

Guild-scoped: applied to ``guild_template`` and every ``guild_<id>``.

Revision ID: 20261006_0462
Revises: 20261006_0461
Create Date: 2026-10-06
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261006_0462"
down_revision = "20261006_0461"
branch_labels = None
depends_on = None


def _upgrade() -> None:
    op.add_column(
        "calendar_events",
        sa.Column("rsvp_open", sa.Boolean(), nullable=False, server_default="true"),
    )


def _downgrade() -> None:
    op.drop_column("calendar_events", "rsvp_open")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _downgrade)
