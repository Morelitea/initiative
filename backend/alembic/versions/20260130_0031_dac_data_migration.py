"""Backfill permissions and drop members_can_write column

Revision ID: 20260130_0031
Revises: 20260130_0030
Create Date: 2026-01-30

Part 2 of DAC refactor: Data migration.
1. Backfills read permissions for all initiative members who don't have permissions
2. Upgrades read to write where members_can_write=true
3. Drops the members_can_write column from projects

After this migration, access is determined solely by:
- Guild admin -> full access
- Initiative PM -> full access
- Explicit ProjectPermission -> use that level
- No permission -> no access (403)
"""

from alembic import op
import sqlalchemy as sa


revision = "20260130_0031"
down_revision = "20260130_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. For ALL existing projects, add read permissions for initiative members
    #    who don't already have explicit permissions
    #    This preserves backward compatibility - all initiative members could previously read
    op.execute("""
        INSERT INTO project_permissions (project_id, user_id, level, guild_id, created_at)
        SELECT p.id, im.user_id, 'read'::project_permission_level, p.guild_id, NOW()
        FROM projects p
        JOIN initiatives i ON p.initiative_id = i.id
        JOIN initiative_members im ON im.initiative_id = i.id
        WHERE NOT EXISTS (
            SELECT 1 FROM project_permissions pp
            WHERE pp.project_id = p.id AND pp.user_id = im.user_id
        )
    """)

    # 2. For projects where members_can_write=true, upgrade read permissions to write
    #    This preserves the existing behavior where members had write access
    op.execute("""
        UPDATE project_permissions pp
        SET level = 'write'::project_permission_level
        FROM projects p
        WHERE pp.project_id = p.id
        AND p.members_can_write = true
        AND pp.level = 'read'::project_permission_level
    """)

    # 3. Drop the members_can_write column - no longer needed
    op.drop_column('projects', 'members_can_write')


def downgrade() -> None:
    # Add back the members_can_write column
    op.add_column(
        'projects',
        sa.Column(
            'members_can_write',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        )
    )

    # Delete read permissions since in the old model, read access was implicit
    op.execute("""
        DELETE FROM project_permissions
        WHERE level = 'read'::project_permission_level
    """)
