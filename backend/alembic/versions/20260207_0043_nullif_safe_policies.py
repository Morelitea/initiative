"""Make all RLS policies NULLIF-safe for empty string session variables

Revision ID: 20260207_0043
Revises: 20260207_0042
Create Date: 2026-02-07

PostgreSQL's current_setting() returns '' (empty string) when a session
variable has never been set, even with missing_ok=true. Casting '' to int
crashes with "invalid input syntax for type integer". This migration wraps
all current_setting(...) casts with NULLIF(..., '') so empty strings become
NULL (fail-closed: 0 rows returned) instead of crashing with 500 errors.
"""

from alembic import op


revision = "20260207_0043"
down_revision = "20260207_0042"
branch_labels = None
depends_on = None

# NULLIF-safe versions of session variable accessors
CURRENT_GUILD_ID = "NULLIF(current_setting('app.current_guild_id', true), '')::int"
CURRENT_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"
CURRENT_GUILD_ROLE = "current_setting('app.current_guild_role', true)"
IS_SUPERADMIN = "current_setting('app.is_superadmin', true) = 'true'"

# Old versions (from 0042) for the downgrade path
OLD_GUILD_ID = "current_setting('app.current_guild_id', true)::int"
OLD_USER_ID = "current_setting('app.current_user_id', true)::int"

# Tables with standard guild_id isolation + superadmin bypass
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
    "tags",
]

JUNCTION_TABLES = ["task_tags", "project_tags", "document_tags"]


def upgrade() -> None:
    # ========================================================================
    # 1. GUILDS table - recreate command-specific policies with NULLIF
    # ========================================================================
    for policy in ("guild_select", "guild_insert", "guild_update", "guild_delete"):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON guilds")

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

    op.execute(f"""
        CREATE POLICY guild_insert ON guilds
        FOR INSERT
        WITH CHECK (
            {CURRENT_USER_ID} IS NOT NULL
            OR {IS_SUPERADMIN}
        )
    """)

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

    op.execute(f"""
        CREATE POLICY guild_delete ON guilds
        FOR DELETE
        USING (
            (id = {CURRENT_GUILD_ID} AND {CURRENT_GUILD_ROLE} = 'admin')
            OR {IS_SUPERADMIN}
        )
    """)

    # ========================================================================
    # 2. GUILD_MEMBERSHIPS - recreate with NULLIF
    # ========================================================================
    for policy in (
        "guild_memberships_select",
        "guild_memberships_insert",
        "guild_memberships_update",
        "guild_memberships_delete",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON guild_memberships")

    op.execute(f"""
        CREATE POLICY guild_memberships_select ON guild_memberships
        FOR SELECT
        USING (
            guild_id = {CURRENT_GUILD_ID}
            OR user_id = {CURRENT_USER_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    op.execute(f"""
        CREATE POLICY guild_memberships_insert ON guild_memberships
        FOR INSERT
        WITH CHECK (
            guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

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

    op.execute(f"""
        CREATE POLICY guild_memberships_delete ON guild_memberships
        FOR DELETE
        USING (
            guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    # ========================================================================
    # 3. Standard guild_id tables - recreate with NULLIF
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
    # 4. document_links - nullable guild_id with NULLIF
    # ========================================================================
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
    # 5. Junction tables - recreate with NULLIF
    # ========================================================================
    for table in JUNCTION_TABLES:
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
    # Restore 0042-style policies (without NULLIF)

    # Guilds
    for policy in ("guild_select", "guild_insert", "guild_update", "guild_delete"):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON guilds")

    op.execute(f"""
        CREATE POLICY guild_select ON guilds
        FOR SELECT
        USING (
            id = {OLD_GUILD_ID}
            OR EXISTS (
                SELECT 1 FROM guild_memberships
                WHERE guild_memberships.guild_id = guilds.id
                AND guild_memberships.user_id = {OLD_USER_ID}
            )
            OR {IS_SUPERADMIN}
        )
    """)

    op.execute(f"""
        CREATE POLICY guild_insert ON guilds
        FOR INSERT
        WITH CHECK (
            {OLD_USER_ID} IS NOT NULL
            OR {IS_SUPERADMIN}
        )
    """)

    op.execute(f"""
        CREATE POLICY guild_update ON guilds
        FOR UPDATE
        USING (
            (id = {OLD_GUILD_ID} AND {CURRENT_GUILD_ROLE} = 'admin')
            OR {IS_SUPERADMIN}
        )
        WITH CHECK (
            (id = {OLD_GUILD_ID} AND {CURRENT_GUILD_ROLE} = 'admin')
            OR {IS_SUPERADMIN}
        )
    """)

    op.execute(f"""
        CREATE POLICY guild_delete ON guilds
        FOR DELETE
        USING (
            (id = {OLD_GUILD_ID} AND {CURRENT_GUILD_ROLE} = 'admin')
            OR {IS_SUPERADMIN}
        )
    """)

    # Guild memberships
    for policy in (
        "guild_memberships_select",
        "guild_memberships_insert",
        "guild_memberships_update",
        "guild_memberships_delete",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON guild_memberships")

    op.execute(f"""
        CREATE POLICY guild_memberships_select ON guild_memberships
        FOR SELECT
        USING (
            guild_id = {OLD_GUILD_ID}
            OR user_id = {OLD_USER_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    op.execute(f"""
        CREATE POLICY guild_memberships_insert ON guild_memberships
        FOR INSERT
        WITH CHECK (
            guild_id = {OLD_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    op.execute(f"""
        CREATE POLICY guild_memberships_update ON guild_memberships
        FOR UPDATE
        USING (
            guild_id = {OLD_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
        WITH CHECK (
            guild_id = {OLD_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    op.execute(f"""
        CREATE POLICY guild_memberships_delete ON guild_memberships
        FOR DELETE
        USING (
            guild_id = {OLD_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    # Standard tables
    for table in STANDARD_GUILD_ID_TABLES:
        op.execute(f"DROP POLICY IF EXISTS guild_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY guild_isolation ON {table}
            FOR ALL
            USING (
                guild_id = {OLD_GUILD_ID}
                OR {IS_SUPERADMIN}
            )
            WITH CHECK (
                guild_id = {OLD_GUILD_ID}
                OR {IS_SUPERADMIN}
            )
        """)

    # document_links
    op.execute("DROP POLICY IF EXISTS guild_isolation ON document_links")
    op.execute(f"""
        CREATE POLICY guild_isolation ON document_links
        FOR ALL
        USING (
            guild_id IS NULL OR guild_id = {OLD_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
        WITH CHECK (
            guild_id IS NULL OR guild_id = {OLD_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    # Junction tables
    for table in JUNCTION_TABLES:
        op.execute(f"DROP POLICY IF EXISTS guild_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY guild_isolation ON {table}
            FOR ALL
            USING (
                EXISTS (
                    SELECT 1 FROM tags
                    WHERE tags.id = {table}.tag_id
                    AND tags.guild_id = {OLD_GUILD_ID}
                )
                OR {IS_SUPERADMIN}
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM tags
                    WHERE tags.id = {table}.tag_id
                    AND tags.guild_id = {OLD_GUILD_ID}
                )
                OR {IS_SUPERADMIN}
            )
        """)
