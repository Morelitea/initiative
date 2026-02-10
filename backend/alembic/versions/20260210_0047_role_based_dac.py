"""Add role-based DAC tables for projects and documents

Revision ID: 20260210_0047
Revises: 20260210_0046
Create Date: 2026-02-10

Adds project_role_permissions and document_role_permissions tables,
enabling access control via initiative roles in addition to
individual user permissions.

Both tables get guild-scoped RLS (PERMISSIVE, matching 0044 pattern)
and initiative-scoped RLS (RESTRICTIVE, matching 0046 pattern).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260210_0047"
down_revision = "20260210_0046"
branch_labels = None
depends_on = None

# Session variable accessors (from 0043/0044/0046)
CURRENT_GUILD_ID = "NULLIF(current_setting('app.current_guild_id', true), '')::int"
CURRENT_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"
IS_SUPERADMIN = "current_setting('app.is_superadmin', true) = 'true'"
IS_GUILD_ADMIN = "current_setting('app.current_guild_role', true) = 'admin'"
BYPASS = f"{IS_GUILD_ADMIN} OR {IS_SUPERADMIN}"

TABLES = ["project_role_permissions", "document_role_permissions"]


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────
    # 1. Create project_role_permissions table
    # ──────────────────────────────────────────────────────────────
    op.create_table(
        "project_role_permissions",
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("initiative_role_id", sa.Integer, sa.ForeignKey("initiative_roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("guild_id", sa.Integer, sa.ForeignKey("guilds.id"), nullable=True),
        sa.Column(
            "level",
            postgresql.ENUM("owner", "write", "read", name="project_permission_level", create_type=False),
            nullable=False,
            server_default="read",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ──────────────────────────────────────────────────────────────
    # 2. Create document_role_permissions table
    # ──────────────────────────────────────────────────────────────
    op.create_table(
        "document_role_permissions",
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("initiative_role_id", sa.Integer, sa.ForeignKey("initiative_roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("guild_id", sa.Integer, sa.ForeignKey("guilds.id"), nullable=True),
        sa.Column(
            "level",
            postgresql.ENUM("owner", "write", "read", name="document_permission_level", create_type=False),
            nullable=False,
            server_default="read",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ──────────────────────────────────────────────────────────────
    # 3. Enable + Force RLS on both tables
    # ──────────────────────────────────────────────────────────────
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # ──────────────────────────────────────────────────────────────
    # 4. Guild-scoped PERMISSIVE policies (matching 0044 pattern)
    # ──────────────────────────────────────────────────────────────
    for table in TABLES:
        # SELECT via guild_memberships
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

        # INSERT scoped to active guild
        op.execute(f"""
            CREATE POLICY guild_insert ON {table}
            FOR INSERT
            WITH CHECK (
                guild_id = {CURRENT_GUILD_ID}
                OR {IS_SUPERADMIN}
            )
        """)

        # UPDATE scoped to active guild
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

        # DELETE scoped to active guild
        op.execute(f"""
            CREATE POLICY guild_delete ON {table}
            FOR DELETE
            USING (
                guild_id = {CURRENT_GUILD_ID}
                OR {IS_SUPERADMIN}
            )
        """)

    # ──────────────────────────────────────────────────────────────
    # 5. Initiative-scoped RESTRICTIVE policies (matching 0046)
    #    Check via initiative_roles → is_initiative_member()
    # ──────────────────────────────────────────────────────────────
    member_check = (
        "EXISTS (\n"
        "                SELECT 1 FROM initiative_roles\n"
        f"                WHERE initiative_roles.id = {{table}}.initiative_role_id\n"
        f"                AND is_initiative_member(initiative_roles.initiative_id, {CURRENT_USER_ID})\n"
        "            )"
    )

    for table in TABLES:
        check = member_check.replace("{table}", table)

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


def downgrade() -> None:
    # Drop all policies
    for table in TABLES:
        for policy in (
            "initiative_member_select",
            "initiative_member_insert",
            "initiative_member_update",
            "initiative_member_delete",
            "guild_select",
            "guild_insert",
            "guild_update",
            "guild_delete",
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")

    # Disable RLS
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Drop tables
    op.drop_table("document_role_permissions")
    op.drop_table("project_role_permissions")
