"""add tags tables for guild-scoped tagging

Revision ID: 20260204_0039
Revises: 709a83dab93d
Create Date: 2026-02-04

"""

revision = '20260204_0039'
down_revision = '709a83dab93d'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # Create tags table
    op.create_table('tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guild_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('color', sa.String(length=7), nullable=False, server_default="'#6366F1'"),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['guild_id'], ['guilds.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tags_guild_id', 'tags', ['guild_id'], unique=False)
    # Case-insensitive uniqueness for tag names within a guild
    op.create_index(
        'ix_tags_guild_name_unique',
        'tags',
        ['guild_id', sa.text('lower(name)')],
        unique=True
    )

    # Create task_tags junction table
    op.create_table('task_tags',
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('task_id', 'tag_id')
    )
    op.create_index('ix_task_tags_task_id', 'task_tags', ['task_id'], unique=False)
    op.create_index('ix_task_tags_tag_id', 'task_tags', ['tag_id'], unique=False)

    # Create project_tags junction table
    op.create_table('project_tags',
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('project_id', 'tag_id')
    )
    op.create_index('ix_project_tags_project_id', 'project_tags', ['project_id'], unique=False)
    op.create_index('ix_project_tags_tag_id', 'project_tags', ['tag_id'], unique=False)

    # Create document_tags junction table
    op.create_table('document_tags',
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('document_id', 'tag_id')
    )
    op.create_index('ix_document_tags_document_id', 'document_tags', ['document_id'], unique=False)
    op.create_index('ix_document_tags_tag_id', 'document_tags', ['tag_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_document_tags_tag_id', table_name='document_tags')
    op.drop_index('ix_document_tags_document_id', table_name='document_tags')
    op.drop_table('document_tags')
    op.drop_index('ix_project_tags_tag_id', table_name='project_tags')
    op.drop_index('ix_project_tags_project_id', table_name='project_tags')
    op.drop_table('project_tags')
    op.drop_index('ix_task_tags_tag_id', table_name='task_tags')
    op.drop_index('ix_task_tags_task_id', table_name='task_tags')
    op.drop_table('task_tags')
    op.drop_index('ix_tags_guild_name_unique', table_name='tags')
    op.drop_index('ix_tags_guild_id', table_name='tags')
    op.drop_table('tags')
