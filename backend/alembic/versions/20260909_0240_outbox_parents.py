"""carry each event's parent chain on the outbox

``event_outbox.parents``: the addressable resources between the resource an
event names and its initiative, innermost first — ``[{"type": "tasks", "id":
4}, {"type": "projects", "id": 7}]`` for a comment on a task. Identifiers, like
every other column here; the capture trigger fills it from the same
``INITIATIVE_PATHS`` walk that already stamps ``initiative_id``.

Defaulted to the empty chain, so rows written before this keep a valid shape
and nothing is backfilled — a chain describes a change that has already been
delivered, and re-deriving one for history would be guesswork about rows whose
parents may since have moved.

Revision ID: 20260909_0240
Revises: 20260909_0239
Create Date: 2026-09-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260909_0240"
down_revision = "20260909_0239"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("event_outbox", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "parents",
                JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            )
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("event_outbox", schema=None) as batch_op:
        batch_op.drop_column("parents")
