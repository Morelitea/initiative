"""an export counts its restarts

An export whose render keeps dying is queued again by the stale sweep each
time. ``restarts`` counts those, so the sweep fails the job once it has been
started over too many times rather than queuing it forever.

Revision ID: 20260925_0398
Revises: 20260925_0397
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260925_0398"
down_revision = "20260925_0397"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("export_jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("restarts", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("export_jobs", schema=None) as batch_op:
        batch_op.drop_column("restarts")
