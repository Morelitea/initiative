"""engagement levels

``engagement_levels``, in every guild schema: one row per item enough people
engaged with lately, holding only a coarse level. The hourly pass writes it.
Its CHECKs and policies are rendered from the model and the registry at boot.

Revision ID: 20261010_0496
Revises: 20261010_0495
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261010_0496"
down_revision = "20261010_0495"
branch_labels = None
depends_on = None


def _create() -> None:
    op.create_table(
        "engagement_levels",
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("entity_type", "entity_id"),
    )


def _drop() -> None:
    op.drop_table("engagement_levels")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _create)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop)
