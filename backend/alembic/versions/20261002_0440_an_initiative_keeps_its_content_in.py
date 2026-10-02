"""an initiative keeps its content in

``initiatives.keep_content_in``: while set, nothing in the initiative is
exported on its own or copied to another initiative. ``resource_actions``
reads it, and is rendered at boot.

Revision ID: 20261002_0440
Revises: 20261002_0439
Create Date: 2026-10-02
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261002_0440"
down_revision = "20261002_0439"
branch_labels = None
depends_on = None


def _add() -> None:
    op.add_column(
        "initiatives",
        sa.Column(
            "keep_content_in", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def _drop() -> None:
    op.drop_column("initiatives", "keep_content_in")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _add)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop)
