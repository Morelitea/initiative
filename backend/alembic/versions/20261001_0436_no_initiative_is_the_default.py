"""no initiative is the default

A community no longer starts with an initiative, so none is singled out: the
one older communities were given is now an initiative like any other, and can
be deleted. Dropping ``is_default`` drops the partial unique index on it too.

Revision ID: 20261001_0436
Revises: 20261001_0435
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261001_0436"
down_revision = "20261001_0435"
branch_labels = None
depends_on = None


def _drop() -> None:
    op.drop_column("initiatives", "is_default")


def _add() -> None:
    op.add_column(
        "initiatives",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index(
        "uq_initiatives_default",
        "initiatives",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _add)
