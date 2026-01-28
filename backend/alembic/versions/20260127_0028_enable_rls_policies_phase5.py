"""Enable Row Level Security and create guild isolation policies (Phase 5 of RLS)

Revision ID: 20260127_0028
Revises: 20260127_0027
Create Date: 2026-01-27

This migration:
1. Enables RLS on all guild-scoped tables
2. Creates guild_isolation policies that filter by app.current_guild_id
3. The policies use current_setting('app.current_guild_id', true)::int to get
   the guild context set by the application via SET LOCAL

Note: Tables with direct guild_id (guilds, guild_memberships, guild_invites,
guild_settings, initiatives) are also included for completeness.

IMPORTANT: The app_admin role (created separately) has BYPASSRLS to allow
migrations and admin operations to work without RLS restrictions.
"""

from alembic import op


revision = "20260127_0028"
down_revision = "20260127_0027"
branch_labels = None
depends_on = None


# All tables that should have RLS enabled
# Tables with direct guild_id
DIRECT_GUILD_TABLES = [
    "guilds",
    "guild_memberships",
    "guild_invites",
    "guild_settings",
    "initiatives",
]

# Tables where we added guild_id (Tier 2 and 3)
DENORMALIZED_GUILD_TABLES = [
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

ALL_TABLES = DIRECT_GUILD_TABLES + DENORMALIZED_GUILD_TABLES


def upgrade() -> None:
    # Enable RLS on all tables
    for table_name in ALL_TABLES:
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        # FORCE ensures RLS applies even to table owners
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")

    # Create policies for the guilds table (special case: filter by id, not guild_id)
    op.execute("""
        CREATE POLICY guild_isolation ON guilds
        FOR ALL
        USING (id = current_setting('app.current_guild_id', true)::int)
        WITH CHECK (id = current_setting('app.current_guild_id', true)::int)
    """)

    # Create policies for tables with guild_id column
    for table_name in DIRECT_GUILD_TABLES[1:] + DENORMALIZED_GUILD_TABLES:
        op.execute(f"""
            CREATE POLICY guild_isolation ON {table_name}
            FOR ALL
            USING (guild_id = current_setting('app.current_guild_id', true)::int)
            WITH CHECK (guild_id = current_setting('app.current_guild_id', true)::int)
        """)


def downgrade() -> None:
    # Drop policies and disable RLS
    for table_name in ALL_TABLES:
        op.execute(f"DROP POLICY IF EXISTS guild_isolation ON {table_name}")
        op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")
