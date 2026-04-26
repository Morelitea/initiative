"""Drop automation tables, role, and the initiatives.automations_enabled column.

Automation orchestration moves to the inititative_infra service. This repo
keeps event publishing only; flow definitions and execution history live
elsewhere now. No data preservation — there are no production rows.

Revision ID: 20260426_0077
Revises: 20260424_0076
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "20260426_0077"
down_revision = "20260424_0076"
branch_labels = None
depends_on = None


_AUTOMATION_TABLES = ("automation_run_steps", "automation_runs", "automation_flows")
_RLS_POLICIES = (
    "guild_isolation",
    "initiative_member_select",
    "initiative_member_insert",
    "initiative_member_update",
    "initiative_member_delete",
)


def upgrade() -> None:
    conn = op.get_bind()

    # Drop RLS policies before the tables — DROP TABLE will fail otherwise.
    for table in _AUTOMATION_TABLES:
        for policy in _RLS_POLICIES:
            conn.execute(text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
        conn.execute(text(f"ALTER TABLE IF EXISTS {table} DISABLE ROW LEVEL SECURITY"))

    # Drop tables in FK-dependency order (steps -> runs -> flows).
    for table in _AUTOMATION_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    # Drop the automation_engine role; revoke first to guard against any
    # leftover grants on tables we keep (initiatives).
    conn.execute(text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'automation_engine') THEN
                REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM automation_engine;
                REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM automation_engine;
                DROP ROLE automation_engine;
            END IF;
        END $$
    """))

    # Drop role-permission rows for automation keys before tightening the
    # CHECK constraint, otherwise the ALTER fails.
    conn.execute(text(
        "DELETE FROM initiative_role_permissions "
        "WHERE permission_key IN ('automations_enabled', 'create_automations')"
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

    # Use raw SQL with IF EXISTS so the migration is idempotent — the column
    # may already be missing in environments that never ran 0067.
    op.execute("ALTER TABLE initiatives DROP COLUMN IF EXISTS automations_enabled")


def downgrade() -> None:
    # Restoring this state means re-running migrations 0067 and 0068. We do
    # not provide a forward-compatible downgrade — the automation domain has
    # been removed from the codebase, so the schemas/policies it referenced
    # no longer exist in the repo. If a deployment needs the old tables back,
    # check out the pre-0077 codebase and roll forward from 0066.
    raise NotImplementedError(
        "Downgrade not supported: automation tables were removed permanently. "
        "To restore, check out a pre-0077 commit and run alembic upgrade from there."
    )
