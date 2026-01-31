"""Backfill document owner permissions

Revision ID: 20260131_0033
Revises: 20260131_0032
Create Date: 2026-01-31

Part 2 of document DAC: Backfill owner permissions for existing documents.
Creates owner permissions for document creators based on created_by_id.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "20260131_0033"
down_revision = "20260131_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create owner permission for document creators who don't have one yet
    op.execute("""
        INSERT INTO document_permissions (document_id, user_id, level, guild_id, created_at)
        SELECT d.id, d.created_by_id, 'owner', d.guild_id, NOW()
        FROM documents d
        WHERE NOT EXISTS (
            SELECT 1 FROM document_permissions dp
            WHERE dp.document_id = d.id AND dp.user_id = d.created_by_id
        )
    """)

    # Upgrade existing permissions for creators to owner
    op.execute("""
        UPDATE document_permissions dp
        SET level = 'owner'
        FROM documents d
        WHERE dp.document_id = d.id
          AND dp.user_id = d.created_by_id
          AND dp.level != 'owner'
    """)


def downgrade() -> None:
    # Convert owner permissions back to write
    op.execute("""
        UPDATE document_permissions
        SET level = 'write'
        WHERE level = 'owner'
    """)
