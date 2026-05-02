"""Add role-level permission keys for the advanced tool.

The 0079 migration only added the per-initiative master switch
(``initiatives.advanced_tool_enabled``). This migration adds the two
role-level permission keys that gate it for individual members:

* ``advanced_tool_enabled`` — can the role view/launch the embedded panel
* ``create_advanced_tool``  — can the role create automations inside it
                              (claim is forwarded to the proprietary
                              backend via the handoff JWT)

The CHECK constraint on ``initiative_role_permissions.permission_key``
is widened to allow the new keys, then a backfill seeds them on every
existing initiative role:

  * Built-in ``project_manager`` (or any ``is_manager=true`` role): both
    permissions ON, matching ``BUILTIN_ROLE_PERMISSIONS`` in code.
  * Everyone else: both permissions OFF (restrictive default).

Revision ID: 20260501_0080
Revises: 20260430_0079
Create Date: 2026-05-01
"""

from alembic import op
from sqlalchemy import text


revision = "20260501_0080"
down_revision = "20260430_0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Widen the CHECK constraint to accept the new permission keys.
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
        "'advanced_tool_enabled', 'create_advanced_tool'))"
    ))

    # Backfill: managers ON, members OFF. Idempotent — only inserts where
    # the row is missing, so re-running on a partially-migrated DB is safe.
    for key in ("advanced_tool_enabled", "create_advanced_tool"):
        conn.execute(text(f"""
            INSERT INTO initiative_role_permissions (initiative_role_id, permission_key, enabled)
            SELECT ir.id, '{key}', ir.is_manager
            FROM initiative_roles ir
            WHERE NOT EXISTS (
                SELECT 1 FROM initiative_role_permissions irp
                WHERE irp.initiative_role_id = ir.id
                  AND irp.permission_key = '{key}'
            )
        """))


def downgrade() -> None:
    conn = op.get_bind()

    # Drop seeded rows BEFORE tightening the CHECK constraint, otherwise
    # the ALTER fails on existing rows that no longer match the predicate.
    conn.execute(text(
        "DELETE FROM initiative_role_permissions "
        "WHERE permission_key IN ('advanced_tool_enabled', 'create_advanced_tool')"
    ))

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
