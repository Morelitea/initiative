"""add the reactions switch to posts

``posts.reactions_enabled``, the counterpart to ``comments_enabled``: a board
can put up a notice people read without reacting to it. Reactions hang off
comments and off posts and off nothing else, so this is a column on ``posts``
rather than a mixin every tool carries.

Defaulted true, so every notice that exists keeps the reactions it takes today
and nothing is backfilled.

Revision ID: 20260907_0237
Revises: 20260907_0236
Create Date: 2026-09-07
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260907_0237"
down_revision = "20260907_0236"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "reactions_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            )
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.drop_column("reactions_enabled")
