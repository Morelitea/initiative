"""Replace FOR ALL guild_isolation with membership-based SELECT policies

Revision ID: 20260207_0044
Revises: 20260207_0043
Create Date: 2026-02-07

The FOR ALL policy on guild-scoped tables uses
  guild_id = current_setting('app.current_guild_id')
which locks SELECT to the active guild only. This breaks cross-guild
reads like My Tasks (scope=global) for non-superadmin users: RLS
silently filters out rows from non-active guilds before the app-level
join on guild_memberships can include them.

Fix: split each FOR ALL policy into four command-specific policies.
SELECT checks guild_memberships (data-driven, deterministic).
INSERT/UPDATE/DELETE remain scoped to the active guild (writes need
guild context).

guilds and guild_memberships already have command-specific policies
from migration 0042/0043 and are not changed here.
"""

from alembic import op


revision = "20260207_0044"
down_revision = "20260207_0043"
branch_labels = None
depends_on = None

# Session variable accessors (NULLIF-safe, from 0043)
CURRENT_GUILD_ID = "NULLIF(current_setting('app.current_guild_id', true), '')::int"
CURRENT_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"
IS_SUPERADMIN = "current_setting('app.is_superadmin', true) = 'true'"

# Tables with a direct guild_id column
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

# Junction tables that link through tags (no direct guild_id)
JUNCTION_TABLES = ["task_tags", "project_tags", "document_tags"]


def _create_membership_select(table: str) -> None:
    """SELECT via guild_memberships — user can read rows from any guild
    they belong to."""
    op.execute(f"""
        CREATE POLICY guild_select ON {table}
        FOR SELECT
        USING (
            EXISTS (
                SELECT 1 FROM guild_memberships
                WHERE guild_memberships.guild_id = {table}.guild_id
                AND guild_memberships.user_id = {CURRENT_USER_ID}
            )
            OR {IS_SUPERADMIN}
        )
    """)


def _create_write_policies(table: str) -> None:
    """INSERT/UPDATE/DELETE scoped to the active guild."""
    op.execute(f"""
        CREATE POLICY guild_insert ON {table}
        FOR INSERT
        WITH CHECK (
            guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    op.execute(f"""
        CREATE POLICY guild_update ON {table}
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
        CREATE POLICY guild_delete ON {table}
        FOR DELETE
        USING (
            guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)


def _drop_command_policies(table: str) -> None:
    """Drop the four command-specific policies created by this migration."""
    for policy in ("guild_select", "guild_insert", "guild_update", "guild_delete"):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")


def upgrade() -> None:
    # ==================================================================
    # 1. Standard guild_id tables — split FOR ALL into 4 policies
    # ==================================================================
    for table in STANDARD_GUILD_ID_TABLES:
        op.execute(f"DROP POLICY IF EXISTS guild_isolation ON {table}")
        _create_membership_select(table)
        _create_write_policies(table)

    # ==================================================================
    # 2. document_links — nullable guild_id, preserve NULL allowance
    # ==================================================================
    op.execute("DROP POLICY IF EXISTS guild_isolation ON document_links")

    # SELECT: membership-based, plus allow rows with NULL guild_id
    op.execute(f"""
        CREATE POLICY guild_select ON document_links
        FOR SELECT
        USING (
            guild_id IS NULL
            OR EXISTS (
                SELECT 1 FROM guild_memberships
                WHERE guild_memberships.guild_id = document_links.guild_id
                AND guild_memberships.user_id = {CURRENT_USER_ID}
            )
            OR {IS_SUPERADMIN}
        )
    """)

    # INSERT: active guild or NULL
    op.execute(f"""
        CREATE POLICY guild_insert ON document_links
        FOR INSERT
        WITH CHECK (
            guild_id IS NULL OR guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    # UPDATE: active guild or NULL
    op.execute(f"""
        CREATE POLICY guild_update ON document_links
        FOR UPDATE
        USING (
            guild_id IS NULL OR guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
        WITH CHECK (
            guild_id IS NULL OR guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    # DELETE: active guild or NULL
    op.execute(f"""
        CREATE POLICY guild_delete ON document_links
        FOR DELETE
        USING (
            guild_id IS NULL OR guild_id = {CURRENT_GUILD_ID}
            OR {IS_SUPERADMIN}
        )
    """)

    # ==================================================================
    # 3. Junction tables — SELECT through tags → guild_memberships
    # ==================================================================
    for table in JUNCTION_TABLES:
        op.execute(f"DROP POLICY IF EXISTS guild_isolation ON {table}")

        # SELECT: membership via tags
        op.execute(f"""
            CREATE POLICY guild_select ON {table}
            FOR SELECT
            USING (
                EXISTS (
                    SELECT 1 FROM tags
                    JOIN guild_memberships ON guild_memberships.guild_id = tags.guild_id
                    WHERE tags.id = {table}.tag_id
                    AND guild_memberships.user_id = {CURRENT_USER_ID}
                )
                OR {IS_SUPERADMIN}
            )
        """)

        # INSERT: active guild via tags
        op.execute(f"""
            CREATE POLICY guild_insert ON {table}
            FOR INSERT
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM tags
                    WHERE tags.id = {table}.tag_id
                    AND tags.guild_id = {CURRENT_GUILD_ID}
                )
                OR {IS_SUPERADMIN}
            )
        """)

        # UPDATE: active guild via tags
        op.execute(f"""
            CREATE POLICY guild_update ON {table}
            FOR UPDATE
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

        # DELETE: active guild via tags
        op.execute(f"""
            CREATE POLICY guild_delete ON {table}
            FOR DELETE
            USING (
                EXISTS (
                    SELECT 1 FROM tags
                    WHERE tags.id = {table}.tag_id
                    AND tags.guild_id = {CURRENT_GUILD_ID}
                )
                OR {IS_SUPERADMIN}
            )
        """)


def downgrade() -> None:
    # Restore FOR ALL guild_isolation policies (from 0043)

    # 1. Standard tables
    for table in STANDARD_GUILD_ID_TABLES:
        _drop_command_policies(table)
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

    # 2. document_links
    _drop_command_policies("document_links")
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

    # 3. Junction tables
    for table in JUNCTION_TABLES:
        _drop_command_policies(table)
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
