"""Add initiative-scoped RESTRICTIVE RLS policies to task tables.

Tasks, task_statuses, subtasks, and task_assignees previously only had
guild-level RLS.  This adds RESTRICTIVE initiative-membership policies
so rows are only visible to members of the owning initiative (or guild
admins / superadmins).

Revision ID: 20260223_0057
Revises: 20260220_0056
Create Date: 2026-02-23
"""

from alembic import op
from sqlalchemy import text

revision = "20260223_0057"
down_revision = "20260220_0056"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# RLS session-variable helpers (same constants used in baseline migration)
# ---------------------------------------------------------------------------
USER_ID = "NULLIF(current_setting('app.current_user_id'::text, true), ''::text)::integer"
GUILD_ROLE = "current_setting('app.current_guild_role'::text, true)"
IS_SUPER = "current_setting('app.is_superadmin'::text, true) = 'true'::text"
IS_ADMIN = f"{GUILD_ROLE} = 'admin'::text"
BYPASS = f"OR ({IS_ADMIN}) OR ({IS_SUPER})"


def _init_member_via_project(table: str, project_col: str = "project_id") -> str:
    """Check initiative membership through a direct project_id FK."""
    return (
        f"EXISTS ("
        f"SELECT 1 FROM projects "
        f"WHERE projects.id = {table}.{project_col} "
        f"AND is_initiative_member(projects.initiative_id, ({USER_ID}))"
        f")"
    )


def _init_member_via_task(table: str, task_col: str = "task_id") -> str:
    """Check initiative membership through task_id → projects."""
    return (
        f"EXISTS ("
        f"SELECT 1 FROM tasks "
        f"JOIN projects ON projects.id = tasks.project_id "
        f"WHERE tasks.id = {table}.{task_col} "
        f"AND is_initiative_member(projects.initiative_id, ({USER_ID}))"
        f")"
    )


def upgrade() -> None:
    conn = op.get_bind()

    # Tables with a direct project_id column
    direct_project_tables = ["tasks", "task_statuses"]
    # Tables that reach projects through tasks
    via_task_tables = ["subtasks", "task_assignees"]

    for table in direct_project_tables:
        expr = f"({_init_member_via_project(table)} {BYPASS})"
        for cmd, policy_name in [
            ("SELECT", "initiative_member_select"),
            ("INSERT", "initiative_member_insert"),
            ("UPDATE", "initiative_member_update"),
            ("DELETE", "initiative_member_delete"),
        ]:
            conn.execute(text(f"DROP POLICY IF EXISTS {policy_name} ON {table}"))
            if cmd == "SELECT":
                conn.execute(text(
                    f"CREATE POLICY {policy_name} ON {table} "
                    f"AS RESTRICTIVE FOR SELECT USING ({expr})"
                ))
            elif cmd == "INSERT":
                conn.execute(text(
                    f"CREATE POLICY {policy_name} ON {table} "
                    f"AS RESTRICTIVE FOR INSERT WITH CHECK ({expr})"
                ))
            elif cmd == "UPDATE":
                conn.execute(text(
                    f"CREATE POLICY {policy_name} ON {table} "
                    f"AS RESTRICTIVE FOR UPDATE USING ({expr}) WITH CHECK ({expr})"
                ))
            elif cmd == "DELETE":
                conn.execute(text(
                    f"CREATE POLICY {policy_name} ON {table} "
                    f"AS RESTRICTIVE FOR DELETE USING ({expr})"
                ))

    for table in via_task_tables:
        expr = f"({_init_member_via_task(table)} {BYPASS})"
        for cmd, policy_name in [
            ("SELECT", "initiative_member_select"),
            ("INSERT", "initiative_member_insert"),
            ("UPDATE", "initiative_member_update"),
            ("DELETE", "initiative_member_delete"),
        ]:
            conn.execute(text(f"DROP POLICY IF EXISTS {policy_name} ON {table}"))
            if cmd == "SELECT":
                conn.execute(text(
                    f"CREATE POLICY {policy_name} ON {table} "
                    f"AS RESTRICTIVE FOR SELECT USING ({expr})"
                ))
            elif cmd == "INSERT":
                conn.execute(text(
                    f"CREATE POLICY {policy_name} ON {table} "
                    f"AS RESTRICTIVE FOR INSERT WITH CHECK ({expr})"
                ))
            elif cmd == "UPDATE":
                conn.execute(text(
                    f"CREATE POLICY {policy_name} ON {table} "
                    f"AS RESTRICTIVE FOR UPDATE USING ({expr}) WITH CHECK ({expr})"
                ))
            elif cmd == "DELETE":
                conn.execute(text(
                    f"CREATE POLICY {policy_name} ON {table} "
                    f"AS RESTRICTIVE FOR DELETE USING ({expr})"
                ))


def downgrade() -> None:
    conn = op.get_bind()
    all_tables = ["tasks", "task_statuses", "subtasks", "task_assignees"]
    policy_names = [
        "initiative_member_select",
        "initiative_member_insert",
        "initiative_member_update",
        "initiative_member_delete",
    ]
    for table in all_tables:
        for policy_name in policy_names:
            conn.execute(text(f"DROP POLICY IF EXISTS {policy_name} ON {table}"))
