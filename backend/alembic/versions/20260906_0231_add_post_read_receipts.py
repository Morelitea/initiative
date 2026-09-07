"""add post read receipts

``post_reads`` is the set of (notice, reader) pairs. A row exists once somebody
has read the post, so unread is the absence of one — which is what makes "mark
unread" a delete rather than a second state to keep consistent with the first.

The board marks a notice read once it has been on screen, so this is written
far more often than it is read, and almost always as a batch of ids from one
page of the feed. The composite primary key is what makes that an idempotent
upsert; the index on ``user_id`` is for the other direction, the unread filter
asking what this reader has already seen.

No FK to ``users``: that table lives in ``public`` and this one is per-guild,
which is the shape every other reader-scoped column in a guild schema takes.
The FK to ``posts`` cascades — a receipt is a fact about a notice, and it goes
when the notice does.

RLS is not applied here. ``post_reads`` is registered in ``INITIATIVE_PATHS``,
so provisioning renders its policies from the registry and the boot backfill
applies them to every guild schema — the registry edit is what bumps the stamp.

Revision ID: 20260906_0231
Revises: 20260906_0230
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260906_0231"
down_revision = "20260906_0230"
branch_labels = None
depends_on = None

#: Asks the next boot to rebuild this guild's search triggers and re-sweep its
#: entries. ``post_reads`` is not itself searchable; the registry it is added to
#: is what the stamp covers.
_CLEAR_SEARCH_GENERATION = "COMMENT ON TABLE search_entries IS NULL"


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.create_table(
        "post_reads",
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("post_id", "user_id"),
    )
    with op.batch_alter_table("post_reads", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_post_reads_user_id"), ["user_id"], unique=False
        )
    op.execute(_CLEAR_SEARCH_GENERATION)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("post_reads", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_post_reads_user_id"))
    op.drop_table("post_reads")
    op.execute(_CLEAR_SEARCH_GENERATION)
