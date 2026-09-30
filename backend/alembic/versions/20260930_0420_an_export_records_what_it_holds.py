"""an export records what it holds

``initiative_ids`` names the initiatives whose content a finished export's
artifact holds, written when it is rendered. The download asks again that the
caller reaches each of them. It is null on every job rendered before this
revision, and the download does not serve those.

Revision ID: 20260930_0420
Revises: 20260930_0419
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260930_0420"
down_revision = "20260930_0419"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("export_jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("initiative_ids", postgresql.ARRAY(sa.Integer()), nullable=True)
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("export_jobs", schema=None) as batch_op:
        batch_op.drop_column("initiative_ids")
