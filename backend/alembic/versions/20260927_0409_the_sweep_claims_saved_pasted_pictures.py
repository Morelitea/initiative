"""the sweep claims saved pasted pictures

``uploads.claimed_at`` records when the pasted-image sweep found a pasted
picture saved, so the sweep looks at each pasted picture once.

Revision ID: 20260927_0409
Revises: 20260927_0408
Create Date: 2026-09-27
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260927_0409"
down_revision = "20260927_0408"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.add_column(
        "uploads", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.drop_column("uploads", "claimed_at")
