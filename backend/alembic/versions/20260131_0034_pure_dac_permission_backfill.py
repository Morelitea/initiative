"""Backfill explicit permissions for guild admins and initiative PMs

Revision ID: 20260131_0034
Revises: 20260131_0033
Create Date: 2026-01-31

This migration supports the switch to pure DAC (Discretionary Access Control).

Previously, guild admins and initiative PMs had implicit access to all
documents and projects in their scope. With pure DAC, access is only
granted through explicit permissions.

This migration backfills read permissions so existing admins/PMs don't lose
access after the code changes.

For documents:
- Guild admins get read permission to all documents in their guild
- Initiative PMs get read permission to all documents in their initiatives

For projects:
- Guild admins get read permission to all projects in their guild
- Initiative PMs get read permission to all projects in their initiatives

Skip users who already have explicit permissions (any level).
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "20260131_0034"
down_revision = "20260131_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Documents ---

    # 1. Guild admins: Grant read permission to all documents in their guild
    op.execute("""
        INSERT INTO document_permissions (document_id, user_id, level, guild_id, created_at)
        SELECT d.id, gm.user_id, 'read', d.guild_id, NOW()
        FROM documents d
        JOIN guild_memberships gm ON gm.guild_id = d.guild_id
        WHERE gm.role = 'admin'
        AND NOT EXISTS (
            SELECT 1 FROM document_permissions dp
            WHERE dp.document_id = d.id AND dp.user_id = gm.user_id
        )
    """)

    # 2. Initiative PMs: Grant read permission to documents in their initiatives
    op.execute("""
        INSERT INTO document_permissions (document_id, user_id, level, guild_id, created_at)
        SELECT d.id, im.user_id, 'read', d.guild_id, NOW()
        FROM documents d
        JOIN initiative_members im ON im.initiative_id = d.initiative_id
        WHERE im.role = 'project_manager'
        AND NOT EXISTS (
            SELECT 1 FROM document_permissions dp
            WHERE dp.document_id = d.id AND dp.user_id = im.user_id
        )
    """)

    # --- Projects ---

    # 3. Guild admins: Grant read permission to all projects in their guild
    op.execute("""
        INSERT INTO project_permissions (project_id, user_id, level, guild_id, created_at)
        SELECT p.id, gm.user_id, 'read'::project_permission_level, p.guild_id, NOW()
        FROM projects p
        JOIN guild_memberships gm ON gm.guild_id = p.guild_id
        WHERE gm.role = 'admin'
        AND NOT EXISTS (
            SELECT 1 FROM project_permissions pp
            WHERE pp.project_id = p.id AND pp.user_id = gm.user_id
        )
    """)

    # 4. Initiative PMs: Grant read permission to projects in their initiatives
    op.execute("""
        INSERT INTO project_permissions (project_id, user_id, level, guild_id, created_at)
        SELECT p.id, im.user_id, 'read'::project_permission_level, p.guild_id, NOW()
        FROM projects p
        JOIN initiative_members im ON im.initiative_id = p.initiative_id
        WHERE im.role = 'project_manager'
        AND NOT EXISTS (
            SELECT 1 FROM project_permissions pp
            WHERE pp.project_id = p.id AND pp.user_id = im.user_id
        )
    """)


def downgrade() -> None:
    # Removing these backfilled permissions is complex because we can't
    # distinguish between permissions created by this migration vs.
    # permissions that were explicitly granted by users.
    #
    # The safe approach is to leave them in place. The downgrade of the
    # code changes will restore implicit access, making these permissions
    # redundant but not harmful.
    pass
