"""a dashboard says whose view it shows

``view_as_user_id`` names the person whose access a dashboard's query widgets
answer from. Empty, the default, is each viewer's own.

Revision ID: 20261004_0453
Revises: 20261003_0452
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261004_0453"
down_revision = "20261003_0452"
branch_labels = None
depends_on = None


def _add() -> None:
    op.add_column(
        "dashboards", sa.Column("view_as_user_id", sa.Integer(), nullable=True)
    )


def _drop() -> None:
    op.drop_column("dashboards", "view_as_user_id")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _add)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop)
