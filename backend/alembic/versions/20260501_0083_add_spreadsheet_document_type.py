"""Add spreadsheet value to the document_type enum.

Adds a new 'spreadsheet' value to the document_type Postgres enum so
documents can be sparse, collaboratively-editable cell grids.

Revision ID: 20260501_0083
Revises: 20260501_0082
Create Date: 2026-05-01
"""

from alembic import op
from sqlalchemy import text

revision = "20260501_0083"
down_revision = "20260501_0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on
    # Postgres versions before 12. autocommit_block() is the supported
    # workaround. Postgres 17 (our target) is fine either way.
    with op.get_context().autocommit_block():
        op.execute(text("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'spreadsheet'"))


def downgrade() -> None:
    # Postgres does not support removing enum values. Existing spreadsheet
    # documents would need to be converted or deleted manually before the
    # value could be dropped via a rebuild of the enum type.
    pass
