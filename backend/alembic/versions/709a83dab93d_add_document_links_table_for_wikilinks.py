"""add document_links table for wikilinks

Revision ID: 709a83dab93d
Revises: 20260202_0038
Create Date: 2026-02-03

"""

revision = '709a83dab93d'
down_revision = '20260202_0038'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table('document_links',
        sa.Column('source_document_id', sa.Integer(), nullable=False),
        sa.Column('target_document_id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['guild_id'], ['guilds.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('source_document_id', 'target_document_id')
    )
    # Add index for efficient backlinks queries
    op.create_index(
        'ix_document_links_target_document_id',
        'document_links',
        ['target_document_id'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_document_links_target_document_id', table_name='document_links')
    op.drop_table('document_links')
