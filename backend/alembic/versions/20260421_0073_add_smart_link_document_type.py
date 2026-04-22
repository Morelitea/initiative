"""Add smart_link value to the document_type enum.

Adds a new 'smart_link' value to the document_type Postgres enum so
documents can be URL-backed iframe embeds (Figma, YouTube, Loom, etc.).

Revision ID: 20260421_0073
Revises: 20260419_0072
Create Date: 2026-04-21
"""

from alembic import op
from sqlalchemy import text

revision = "20260421_0073"
down_revision = "20260419_0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on
    # Postgres versions before 12. autocommit_block() is the supported
    # workaround. Postgres 17 (our target) is fine either way.
    with op.get_context().autocommit_block():
        op.execute(text("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'smart_link'"))


def downgrade() -> None:
    # Postgres does not support removing enum values. Existing smart_link
    # documents would need to be converted or deleted manually before the
    # value could be dropped via a rebuild of the enum type.
    pass
