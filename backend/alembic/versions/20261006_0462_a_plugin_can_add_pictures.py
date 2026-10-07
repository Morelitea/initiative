"""a plug-in can add pictures

``galleries:write`` now reaches a gallery's pictures and their versions, the
way ``wikis:write`` reaches a wiki's pages. A plug-in writes with no person in
context, so the ``fn_set_created_by`` trigger leaves ``created_by`` NULL on the
picture, its version and the stored file, as it does on every other table a
scope writes (``20260924_0375``). Those three drop their NOT NULL to the
mixin's floor.

Revision ID: 20261006_0462
Revises: 20261006_0461
Create Date: 2026-10-06
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261006_0462"
down_revision = "20261006_0461"
branch_labels = None
depends_on = None


_TABLES = ("gallery_images", "gallery_image_versions", "uploads")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    for table in _TABLES:
        op.alter_column(table, "created_by", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        if bind.execute(
            sa.text(f"SELECT 1 FROM {table} WHERE created_by IS NULL LIMIT 1")
        ).first():
            raise NotImplementedError(
                "A picture, picture version or upload a plug-in added has no "
                "creator, so created_by cannot be made NOT NULL again without "
                "losing those rows. Roll forward, or restore from a backup taken "
                "before this revision."
            )
    for table in _TABLES:
        op.alter_column(table, "created_by", existing_type=sa.Integer(), nullable=False)
