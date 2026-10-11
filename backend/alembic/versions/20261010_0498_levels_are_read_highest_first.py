"""levels are read highest first

An index on ``engagement_levels (level, entity_type, entity_id)``, in every
guild schema, so a picker reads the highest levels in order and stops at its
limit.

Revision ID: 20261010_0498
Revises: 20261010_0497
Create Date: 2026-10-10
"""

from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261010_0498"
down_revision = "20261010_0497"
branch_labels = None
depends_on = None

INDEX = "ix_engagement_levels_level"


def upgrade() -> None:
    run_for_each_guild_schema(
        op.get_bind(),
        lambda: op.create_index(
            INDEX, "engagement_levels", ["level", "entity_type", "entity_id"]
        ),
    )


def downgrade() -> None:
    run_for_each_guild_schema(
        op.get_bind(), lambda: op.drop_index(INDEX, table_name="engagement_levels")
    )
