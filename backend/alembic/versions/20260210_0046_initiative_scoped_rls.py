"""Add initiative-scoped RLS policies

Revision ID: 20260210_0046
Revises: 20260208_0045
Create Date: 2026-02-10

Adds a second RLS layer that restricts access to initiative-scoped data
based on initiative_members membership. Guild admins and superadmins
bypass this layer entirely.

Tables with existing guild RLS get RESTRICTIVE policies (ANDed with
existing PERMISSIVE guild policies). Tables without existing RLS
(initiative_roles, initiative_role_permissions) get new PERMISSIVE
policies with RLS enabled.

A SECURITY DEFINER helper function avoids recursive RLS when the
initiative_members table's own policy queries initiative_members.
"""

from alembic import op


revision = "20260210_0046"
down_revision = "20260208_0045"
branch_labels = None
depends_on = None

# Session variable accessors (NULLIF-safe, from 0043/0044)
CURRENT_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"
IS_SUPERADMIN = "current_setting('app.is_superadmin', true) = 'true'"
IS_GUILD_ADMIN = "current_setting('app.current_guild_role', true) = 'admin'"
BYPASS = f"{IS_GUILD_ADMIN} OR {IS_SUPERADMIN}"

# Tables with existing guild RLS — get RESTRICTIVE initiative policies
RESTRICTIVE_TABLES_DIRECT = ["initiatives", "initiative_members", "projects", "documents"]

# Tables without existing RLS — get PERMISSIVE initiative policies + RLS enabled
PERMISSIVE_TABLES = ["initiative_roles", "initiative_role_permissions"]


def _initiative_id_expr(table: str) -> str:
    """Return the SQL expression to get initiative_id for a given table."""
    if table == "initiatives":
        return f"{table}.id"
    if table == "initiative_role_permissions":
        # Join through initiative_roles since this table has no direct initiative_id
        return None  # handled separately
    return f"{table}.initiative_id"


def _member_check(table: str) -> str:
    """Return the membership check clause for a table."""
    if table == "initiative_role_permissions":
        return (
            "EXISTS (\n"
            "                SELECT 1 FROM initiative_roles\n"
            "                WHERE initiative_roles.id = initiative_role_permissions.initiative_role_id\n"
            f"                AND is_initiative_member(initiative_roles.initiative_id, {CURRENT_USER_ID})\n"
            "            )"
        )
    init_id = _initiative_id_expr(table)
    return f"is_initiative_member({init_id}, {CURRENT_USER_ID})"


def _create_restrictive_policies(table: str) -> None:
    """Create 4 RESTRICTIVE initiative-scoped policies on a table with existing guild RLS."""
    check = _member_check(table)

    op.execute(f"""
        CREATE POLICY initiative_member_select ON {table}
        AS RESTRICTIVE
        FOR SELECT
        USING (
            {check}
            OR {BYPASS}
        )
    """)

    op.execute(f"""
        CREATE POLICY initiative_member_insert ON {table}
        AS RESTRICTIVE
        FOR INSERT
        WITH CHECK (
            {check}
            OR {BYPASS}
        )
    """)

    op.execute(f"""
        CREATE POLICY initiative_member_update ON {table}
        AS RESTRICTIVE
        FOR UPDATE
        USING (
            {check}
            OR {BYPASS}
        )
        WITH CHECK (
            {check}
            OR {BYPASS}
        )
    """)

    op.execute(f"""
        CREATE POLICY initiative_member_delete ON {table}
        AS RESTRICTIVE
        FOR DELETE
        USING (
            {check}
            OR {BYPASS}
        )
    """)


def _create_permissive_policies(table: str) -> None:
    """Create 4 PERMISSIVE initiative-scoped policies on a table without existing RLS."""
    check = _member_check(table)

    op.execute(f"""
        CREATE POLICY initiative_member_select ON {table}
        FOR SELECT
        USING (
            {check}
            OR {BYPASS}
        )
    """)

    op.execute(f"""
        CREATE POLICY initiative_member_insert ON {table}
        FOR INSERT
        WITH CHECK (
            {check}
            OR {BYPASS}
        )
    """)

    op.execute(f"""
        CREATE POLICY initiative_member_update ON {table}
        FOR UPDATE
        USING (
            {check}
            OR {BYPASS}
        )
        WITH CHECK (
            {check}
            OR {BYPASS}
        )
    """)

    op.execute(f"""
        CREATE POLICY initiative_member_delete ON {table}
        FOR DELETE
        USING (
            {check}
            OR {BYPASS}
        )
    """)


def _drop_initiative_policies(table: str) -> None:
    """Drop all 4 initiative-scoped policies from a table."""
    for policy in (
        "initiative_member_select",
        "initiative_member_insert",
        "initiative_member_update",
        "initiative_member_delete",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")


def upgrade() -> None:
    # 1. Create SECURITY DEFINER helper function
    #    This avoids recursive RLS when initiative_members' own policy
    #    queries initiative_members.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION is_initiative_member(p_initiative_id int, p_user_id int)
        RETURNS boolean
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        SET search_path = public
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM initiative_members
                WHERE initiative_id = p_initiative_id
                AND user_id = p_user_id
            )
        $$
    """)

    # Harden: revoke default public execute, grant only to app_user
    op.execute("REVOKE EXECUTE ON FUNCTION is_initiative_member(int, int) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION is_initiative_member(int, int) TO app_user")

    # 2. Add RESTRICTIVE policies on tables with existing guild RLS
    for table in RESTRICTIVE_TABLES_DIRECT:
        _create_restrictive_policies(table)

    # 3. Enable + Force RLS on initiative_roles and initiative_role_permissions
    for table in PERMISSIVE_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # 4. Add PERMISSIVE policies on newly RLS-enabled tables
    for table in PERMISSIVE_TABLES:
        _create_permissive_policies(table)


def downgrade() -> None:
    # 1. Drop all initiative-scoped policies
    for table in RESTRICTIVE_TABLES_DIRECT + PERMISSIVE_TABLES:
        _drop_initiative_policies(table)

    # 2. Disable RLS on tables that didn't have it before
    for table in PERMISSIVE_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # 3. Drop the helper function
    op.execute("DROP FUNCTION IF EXISTS is_initiative_member(int, int)")
