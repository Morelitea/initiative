"""plug-ins keep metadata

``plugin_metadata``, in every guild schema: the values an installed plug-in
keeps in Initiative, one row per key, on an item or on the install itself
(``entity_type = 'plugin'``, ``entity_id`` the install's id). The rows go
with the install. Its policies and the plug-in role's grants are rendered by
the provisioning run.

Revision ID: 20261009_0476
Revises: 20261009_0475
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261009_0476"
down_revision = "20261009_0475"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.create_table(
        "plugin_metadata",
        sa.Column("install_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("lookup", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('task', 'queue_item', 'calendar_event', 'counter', "
            "'gallery_image', 'post', 'plugin')",
            name="ck_plugin_metadata_entity_type",
        ),
        sa.ForeignKeyConstraint(
            ["install_id"], ["guild_plugins.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("install_id", "entity_type", "entity_id", "key"),
    )
    op.create_index(
        "ix_plugin_metadata_lookup",
        "plugin_metadata",
        ["install_id", "key", "lookup"],
        unique=False,
        postgresql_where=sa.text("lookup IS NOT NULL"),
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.drop_index("ix_plugin_metadata_lookup", table_name="plugin_metadata")
    op.drop_table("plugin_metadata")
