"""plug-in values are shown

``plugin_metadata.shown``, in every guild schema: whether the install's pinned
version declares the key as a field on the item's kind, which is what lets a
reader of the item read the value. Every row starts unshown; the install's
next write, or its next version, sets it. ``ix_plugin_metadata_entity`` finds
an item's values from every install at once. The read policy is rendered by
the provisioning run.

Revision ID: 20261009_0480
Revises: 20261009_0479
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261009_0480"
down_revision = "20261009_0479"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.add_column(
        "plugin_metadata",
        sa.Column(
            "shown", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.create_index(
        "ix_plugin_metadata_entity",
        "plugin_metadata",
        ["entity_type", "entity_id"],
        unique=False,
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.drop_index("ix_plugin_metadata_entity", table_name="plugin_metadata")
    op.drop_column("plugin_metadata", "shown")
