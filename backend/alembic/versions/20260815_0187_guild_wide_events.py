"""Allow guild-wide events in the outbox

Guild-content migration. ``event_outbox.initiative_id`` becomes nullable so a
row that belongs to no initiative — a tag, which is guild-level and shared
across initiatives — can be captured at all.

A NULL there is read by ``initiative_access`` as "the initiative gate has
nothing to decide", admitting any guild member. That is the correct disclosure
for these rows: they are guild-level precisely because they belong to no
initiative, and every member can already read them, so an event naming one
reveals nothing new. Envelopes carry ids and column names, never values.

The capture function is redeployed with it: a NULL is now expected where a
registry says the table is guild-wide, and still means "skip" everywhere else,
so an initiative-scoped row whose lookup fails is not broadcast without a scope.

Revision ID: 20260815_0187
Revises: 20260815_0186
Create Date: 2026-08-15
"""

from __future__ import annotations

from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260815_0187"
down_revision = "20260815_0186"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.alter_column("event_outbox", "initiative_id", nullable=True)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.execute("DELETE FROM event_outbox WHERE initiative_id IS NULL")
    op.alter_column("event_outbox", "initiative_id", nullable=False)
