"""Refine RLS policies: guild command-specific, membership SELECT split, super admin bypass

Revision ID: 20260207_0042
Revises: 20260207_0041
Create Date: 2026-02-07

Replaces the blanket guild_isolation FOR ALL policies with:
- Guild table: command-specific SELECT/INSERT/UPDATE/DELETE policies
- Guild memberships: separate SELECT (cross-guild for own memberships) and write
- All tables: super admin bypass via app.is_superadmin session variable
"""

from alembic import op


revision = "20260207_0042"
down_revision = "20260207_0041"
branch_labels = None
depends_on = None

CURRENT_GUILD_ID = "current_setting('app.current_guild_id', true)::int"
CURRENT_USER_ID = "current_setting('app.current_user_id', true)::int"
CURRENT_GUILD_ROLE = "current_setting('app.current_guild_role', true)"
IS_SUPERADMIN = "current_setting('app.is_superadmin', true) = 'true'"

# Tables with guild_id that get the standard guild isolation + superadmin bypass
STANDARD_GUILD_ID_TABLES = [
    "guild_invites",
    "guild_settings",
    "initiatives",
    "projects",
    "documents",
    "initiative_members",
    "tasks",
    "task_statuses",
    "subtasks",
    "task_assignees",
    "comments",
    "project_permissions",
    "project_favorites",
    "recent_project_views",
    "project_orders",
    "project_documents",
    "document_permissions",
]

# New tables from the previous migration also need superadmin bypass
NEW_DIRECT_TABLES = ["tags", "document_links"]
NEW_JUNCTION_TABLES = ["task_tags", "project_tags", "document_tags"]


def upgrade() -> None:
    # ========================================================================
    # 1. GUILDS table - replace single FOR ALL with command-specific policies
    # ========================================================================
    op.execute("DROP POLICY IF EXISTS guild_isolation ON guilds")

    # SELECT: own guild, any guild user is a member of, or superadmin
    op.execute(f"""
        CREATE POLICY guild_select ON guilds
        FOR SELECT
        USING (
            id = {CURRENT_GUILD_ID}
            OR EXISTS (
                SELECT 1 FROM guild_memberships
                WHERE guild_memberships.guild_id = guilds.id
                AND guild_memberships.user_id = {CURRENT_USER_ID}
            )
            OR {IS_SUPERADMIN}
        )
    """)

    # INSERT: any authenticated user can create a guild (app-level DISABLE_GUILD_CREATION check remains)
    op.execute(f"""
        CREATE POLICY guild_insert ON guilds
        FOR INSERT
        WITH CHECK (
            {CURRENT_USER_ID} IS NOT NULL
            OR {IS_SUPERADMIN}
        )
    """)

    # UPDATE: guild admin or superadmin
    op.execute(f"""
        CREATE POLICY guild_update ON guilds
        FOR UPDATE
        USING (
            (id = {CURRENT_GUILD_ID} AND {CURRENT_GUILD_ROLE} = 'admin')
            OR {IS_SUPERADMIN}
        )
        WITH CHECK (
            (id = {CURRENT_GUILD_ID} AND {CURRENT_GUILD_ROLE} = 'admin')
            OR {IS_SUPERADMIN}
        )
    """)

    # DELETE: guild admin or superadmin
    op.execute(f"""
        CREATE POLICY guild_delete ON guilds
        FOR DELETE
        USING (
            (id = {CURRENT_GUILD_ID} AND {CURRENT_GUILD_ROLE} = 'admin')
            OR {IS_SUPERADMIN}
        )
    """)

    # ========================================================================
    # 2. GUILD_MEMBERSHIPS - split SELECT from write operations
    # ========================================================================
    op.execute("DROP POLICY IF EXISTS guild_isolation ON guild_memberships")

    # SELECT: own guild, own memberships across guilds, or superadmin
    op.execute(f"""
        CREATE POLICY guild_memberships_select ON guild_memberships
        FOR SELECT
        USING (
            guild_id = {CURRENT_GUILD_ID}
            OR user_id = {CURRENT_USER_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    # INSERT: current guild or superadmin
    op.execute(f"""
        CREATE POLICY guild_memberships_insert ON guild_memberships
        FOR INSERT
        WITH CHECK (
            guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    # UPDATE: current guild or superadmin
    op.execute(f"""
        CREATE POLICY guild_memberships_update ON guild_memberships
        FOR UPDATE
        USING (
            guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
        WITH CHECK (
            guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    # DELETE: current guild or superadmin
    op.execute(f"""
        CREATE POLICY guild_memberships_delete ON guild_memberships
        FOR DELETE
        USING (
            guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    # ========================================================================
    # 3. Standard guild_id tables - drop old policy, recreate with superadmin
    # ========================================================================
    for table in STANDARD_GUILD_ID_TABLES:
        op.execute(f"DROP POLICY IF EXISTS guild_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY guild_isolation ON {table}
            FOR ALL
            USING (
                guild_id = {CURRENT_GUILD_ID}
                OR {IS_SUPERADMIN}
            )
            WITH CHECK (
                guild_id = {CURRENT_GUILD_ID}
                OR {IS_SUPERADMIN}
            )
        """)

    # ========================================================================
    # 4. New direct guild_id tables - recreate with superadmin bypass
    # ========================================================================
    # tags: direct guild_id
    op.execute("DROP POLICY IF EXISTS guild_isolation ON tags")
    op.execute(f"""
        CREATE POLICY guild_isolation ON tags
        FOR ALL
        USING (
            guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
        WITH CHECK (
            guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    # document_links: nullable guild_id
    op.execute("DROP POLICY IF EXISTS guild_isolation ON document_links")
    op.execute(f"""
        CREATE POLICY guild_isolation ON document_links
        FOR ALL
        USING (
            guild_id IS NULL OR guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
        WITH CHECK (
            guild_id IS NULL OR guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    # ========================================================================
    # 5. Junction tables - recreate with superadmin bypass
    # ========================================================================
    for table in NEW_JUNCTION_TABLES:
        op.execute(f"DROP POLICY IF EXISTS guild_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY guild_isolation ON {table}
            FOR ALL
            USING (
                EXISTS (
                    SELECT 1 FROM tags
                    WHERE tags.id = {table}.tag_id
                    AND tags.guild_id = {CURRENT_GUILD_ID}
                )
                OR {IS_SUPERADMIN}
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM tags
                    WHERE tags.id = {table}.tag_id
                    AND tags.guild_id = {CURRENT_GUILD_ID}
                )
                OR {IS_SUPERADMIN}
            )
        """)


def downgrade() -> None:
    # Restore original guild_isolation FOR ALL policies

    # Guilds: drop command-specific, restore simple FOR ALL
    for policy in ("guild_select", "guild_insert", "guild_update", "guild_delete"):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON guilds")
    op.execute(f"""
        CREATE POLICY guild_isolation ON guilds
        FOR ALL
        USING (id = {CURRENT_GUILD_ID})
        WITH CHECK (id = {CURRENT_GUILD_ID})
    """)

    # Guild memberships: drop split policies, restore simple FOR ALL
    for policy in (
        "guild_memberships_select",
        "guild_memberships_insert",
        "guild_memberships_update",
        "guild_memberships_delete",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON guild_memberships")
    op.execute(f"""
        CREATE POLICY guild_isolation ON guild_memberships
        FOR ALL
        USING (guild_id = {CURRENT_GUILD_ID})
        WITH CHECK (guild_id = {CURRENT_GUILD_ID})
    """)

    # Standard tables: drop and recreate without superadmin bypass
    for table in STANDARD_GUILD_ID_TABLES:
        op.execute(f"DROP POLICY IF EXISTS guild_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY guild_isolation ON {table}
            FOR ALL
            USING (guild_id = {CURRENT_GUILD_ID})
            WITH CHECK (guild_id = {CURRENT_GUILD_ID})
        """)

    # tags
    op.execute("DROP POLICY IF EXISTS guild_isolation ON tags")
    op.execute(f"""
        CREATE POLICY guild_isolation ON tags
        FOR ALL
        USING (guild_id = {CURRENT_GUILD_ID})
        WITH CHECK (guild_id = {CURRENT_GUILD_ID})
    """)

    # document_links
    op.execute("DROP POLICY IF EXISTS guild_isolation ON document_links")
    op.execute(f"""
        CREATE POLICY guild_isolation ON document_links
        FOR ALL
        USING (guild_id IS NULL OR guild_id = {CURRENT_GUILD_ID})
        WITH CHECK (guild_id IS NULL OR guild_id = {CURRENT_GUILD_ID})
    """)

    # Junction tables
    for table in NEW_JUNCTION_TABLES:
        op.execute(f"DROP POLICY IF EXISTS guild_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY guild_isolation ON {table}
            FOR ALL
            USING (
                EXISTS (
                    SELECT 1 FROM tags
                    WHERE tags.id = {table}.tag_id
                    AND tags.guild_id = {CURRENT_GUILD_ID}
                )
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM tags
                    WHERE tags.id = {table}.tag_id
                    AND tags.guild_id = {CURRENT_GUILD_ID}
                )
            )
        """)
