"""Add 'read' level to project permission enum

Revision ID: 20260130_0030
Revises: 20260127_0029
Create Date: 2026-01-30

Part 1 of DAC refactor: Add the 'read' enum value.
This is a separate migration because ALTER TYPE ADD VALUE cannot be
rolled back within a transaction, and we want atomic data migration.

See 20260130_0031 for the data migration that uses this new value.
"""

from alembic import op


revision = "20260130_0030"
down_revision = "20260127_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'read' value to the project_permission_level enum
    # This cannot run in a transaction in PostgreSQL, but Alembic handles
    # the commit boundary between migrations automatically
    op.execute("ALTER TYPE project_permission_level ADD VALUE IF NOT EXISTS 'read'")


def downgrade() -> None:
    # We cannot easily remove an enum value in PostgreSQL
    # The 'read' value will remain in the enum but won't be used
    # To fully clean up, you'd need to:
    # 1. Create a new enum without 'read'
    # 2. Alter the column to use the new enum
    # 3. Drop the old enum
    # This is complex and rarely needed for downgrades
    pass
