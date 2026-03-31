"""Add automations_enabled column to initiatives and backfill role permissions.

Revision ID: 20260330_0067
Revises: 20260325_0066
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "20260330_0067"
down_revision = "20260325_0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # -- Add automations_enabled to initiatives --
    op.add_column(
        "initiatives",
        sa.Column("automations_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )

    # -- Update permission_key check constraint --
    conn.execute(text(
        "ALTER TABLE initiative_role_permissions "
        "DROP CONSTRAINT IF EXISTS ck_initiative_role_permissions_permission_key"
    ))
    conn.execute(text(
        "ALTER TABLE initiative_role_permissions "
        "ADD CONSTRAINT ck_initiative_role_permissions_permission_key "
        "CHECK (permission_key IN ("
        "'docs_enabled', 'projects_enabled', 'create_docs', 'create_projects', "
        "'queues_enabled', 'create_queues', "
        "'events_enabled', 'create_events', "
        "'automations_enabled', 'create_automations'))"
    ))

    # -- Backfill initiative role permissions --
    conn.execute(text("""
        INSERT INTO initiative_role_permissions (initiative_role_id, permission_key, enabled)
        SELECT ir.id, 'automations_enabled', ir.is_manager
        FROM initiative_roles ir
        WHERE NOT EXISTS (
            SELECT 1 FROM initiative_role_permissions irp
            WHERE irp.initiative_role_id = ir.id AND irp.permission_key = 'automations_enabled'
        )
    """))
    conn.execute(text("""
        INSERT INTO initiative_role_permissions (initiative_role_id, permission_key, enabled)
        SELECT ir.id, 'create_automations', ir.is_manager
        FROM initiative_roles ir
        WHERE NOT EXISTS (
            SELECT 1 FROM initiative_role_permissions irp
            WHERE irp.initiative_role_id = ir.id AND irp.permission_key = 'create_automations'
        )
    """))


def downgrade() -> None:
    conn = op.get_bind()

    # Remove backfilled permissions
    conn.execute(text(
        "DELETE FROM initiative_role_permissions "
        "WHERE permission_key IN ('automations_enabled', 'create_automations')"
    ))

    # Restore permission_key check constraint
    conn.execute(text(
        "ALTER TABLE initiative_role_permissions "
        "DROP CONSTRAINT IF EXISTS ck_initiative_role_permissions_permission_key"
    ))
    conn.execute(text(
        "ALTER TABLE initiative_role_permissions "
        "ADD CONSTRAINT ck_initiative_role_permissions_permission_key "
        "CHECK (permission_key IN ("
        "'docs_enabled', 'projects_enabled', 'create_docs', 'create_projects', "
        "'queues_enabled', 'create_queues', "
        "'events_enabled', 'create_events'))"
    ))

    # Remove automations_enabled from initiatives
    op.drop_column("initiatives", "automations_enabled")
