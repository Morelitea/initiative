"""an export may be delivered instead of downloaded

Adds ``export_jobs.destination_ref``: where an archive too large to hand back
over HTTP was written instead. Exactly one of ``artifact_ref`` and this is set
on a finished job.

Nullable, so every job already recorded reads as one the app held itself —
which is what all of them were.

Revision ID: 20260920_0328
Revises: 20260920_0327
Create Date: 2026-09-20
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes  # noqa: F401 — AutoString below resolves through it
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260920_0328"
down_revision = "20260920_0327"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("export_jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "destination_ref", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("export_jobs", schema=None) as batch_op:
        batch_op.drop_column("destination_ref")
