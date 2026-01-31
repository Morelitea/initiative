"""Add owner to document_permission_level enum

Revision ID: 20260131_0032
Revises: 20260130_0031
Create Date: 2026-01-31

Part 1 of document DAC: Add the 'owner' enum value.
This is a separate migration because PostgreSQL requires new enum values
to be committed before they can be used in DML statements.

See 20260131_0033 for the data migration that uses this new value.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "20260131_0032"
down_revision = "20260130_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'owner' value to document_permission_level enum
    op.execute("ALTER TYPE document_permission_level ADD VALUE IF NOT EXISTS 'owner'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values directly.
    # The 'owner' value will remain in the enum but won't be used.
    pass
