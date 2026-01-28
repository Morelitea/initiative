"""Add guild_id columns to tier 2/3 tables (Phase 1 of RLS)

Revision ID: 20260127_0025
Revises: 20260127_0024
Create Date: 2026-01-27

This migration adds nullable guild_id columns to all tables that need
guild-scoped Row Level Security (RLS). The columns are nullable initially
to allow backfilling existing data in a separate migration.

Tables modified:
- Tier 2 (via initiative): projects, documents, initiative_members
- Tier 3 (via project): tasks, task_statuses, subtasks, task_assignees,
  comments, project_permissions, project_favorites, recent_project_views,
  project_orders, project_documents, document_permissions
"""

from alembic import op
import sqlalchemy as sa


revision = "20260127_0025"
down_revision = "20260127_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tier 2 tables (get guild_id from initiative)
    op.add_column("projects", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.add_column("initiative_members", sa.Column("guild_id", sa.Integer(), nullable=True))

    # Tier 3 tables (get guild_id from project or document)
    op.add_column("tasks", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.add_column("task_statuses", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.add_column("subtasks", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.add_column("task_assignees", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.add_column("comments", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.add_column("project_permissions", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.add_column("project_favorites", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.add_column("recent_project_views", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.add_column("project_orders", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.add_column("project_documents", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.add_column("document_permissions", sa.Column("guild_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    # Remove columns in reverse order
    op.drop_column("document_permissions", "guild_id")
    op.drop_column("project_documents", "guild_id")
    op.drop_column("project_orders", "guild_id")
    op.drop_column("recent_project_views", "guild_id")
    op.drop_column("project_favorites", "guild_id")
    op.drop_column("project_permissions", "guild_id")
    op.drop_column("comments", "guild_id")
    op.drop_column("task_assignees", "guild_id")
    op.drop_column("subtasks", "guild_id")
    op.drop_column("task_statuses", "guild_id")
    op.drop_column("tasks", "guild_id")
    op.drop_column("initiative_members", "guild_id")
    op.drop_column("documents", "guild_id")
    op.drop_column("projects", "guild_id")
