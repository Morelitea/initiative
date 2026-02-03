"""Add initiative role permissions tables

Revision ID: 20260202_0038
Revises: 20260202_0037
Create Date: 2026-02-02

Creates configurable role-based permissions per initiative:
1. Create initiative_roles table for defining roles per initiative
2. Create initiative_role_permissions table for permission toggles
3. Seed built-in PM/Member roles for all existing initiatives
4. Add role_id FK to initiative_members
5. Migrate existing role enum values to role_id FK
6. Drop old role column and enum
"""

from alembic import op
import sqlalchemy as sa

revision = "20260202_0038"
down_revision = "20260202_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create initiative_roles table
    op.create_table(
        "initiative_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "initiative_id",
            sa.Integer(),
            sa.ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_manager", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("initiative_id", "name", name="uq_initiative_role_name"),
    )
    op.create_index(
        "ix_initiative_roles_initiative_id",
        "initiative_roles",
        ["initiative_id"],
    )

    # 2. Create initiative_role_permissions table
    op.create_table(
        "initiative_role_permissions",
        sa.Column(
            "initiative_role_id",
            sa.Integer(),
            sa.ForeignKey("initiative_roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("permission_key", sa.String(length=50), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
    )

    # 3. Seed built-in roles for all existing initiatives
    # First, create PM roles
    op.execute("""
        INSERT INTO initiative_roles (initiative_id, name, display_name, is_builtin, is_manager, position)
        SELECT id, 'project_manager', 'Project Manager', true, true, 0
        FROM initiatives
    """)
    # Then, create Member roles
    op.execute("""
        INSERT INTO initiative_roles (initiative_id, name, display_name, is_builtin, is_manager, position)
        SELECT id, 'member', 'Member', true, false, 1
        FROM initiatives
    """)

    # 4. Seed permissions for built-in roles
    # PM gets all permissions enabled
    op.execute("""
        INSERT INTO initiative_role_permissions (initiative_role_id, permission_key, enabled)
        SELECT ir.id, perm.key, true
        FROM initiative_roles ir
        CROSS JOIN (VALUES
            ('docs_enabled'),
            ('projects_enabled'),
            ('create_docs'),
            ('create_projects')
        ) AS perm(key)
        WHERE ir.name = 'project_manager'
    """)
    # Member gets feature access but not create permissions
    op.execute("""
        INSERT INTO initiative_role_permissions (initiative_role_id, permission_key, enabled)
        SELECT ir.id, perm.key, perm.enabled
        FROM initiative_roles ir
        CROSS JOIN (VALUES
            ('docs_enabled', true),
            ('projects_enabled', true),
            ('create_docs', false),
            ('create_projects', false)
        ) AS perm(key, enabled)
        WHERE ir.name = 'member'
    """)

    # 5. Add role_id column to initiative_members
    op.add_column(
        "initiative_members",
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("initiative_roles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_initiative_members_role_id",
        "initiative_members",
        ["role_id"],
    )

    # 6. Migrate existing role enum values to role_id FK
    # Map project_manager enum to PM role
    op.execute("""
        UPDATE initiative_members im
        SET role_id = ir.id
        FROM initiative_roles ir
        WHERE ir.initiative_id = im.initiative_id
        AND ir.name = 'project_manager'
        AND im.role = 'project_manager'
    """)
    # Map member enum to Member role
    op.execute("""
        UPDATE initiative_members im
        SET role_id = ir.id
        FROM initiative_roles ir
        WHERE ir.initiative_id = im.initiative_id
        AND ir.name = 'member'
        AND im.role = 'member'
    """)

    # 7. Drop old role column and enum
    op.drop_column("initiative_members", "role")
    op.execute("DROP TYPE IF EXISTS initiative_role")


def downgrade() -> None:
    # 1. Re-create the enum type
    op.execute("CREATE TYPE initiative_role AS ENUM ('project_manager', 'member')")

    # 2. Add back the role column
    op.add_column(
        "initiative_members",
        sa.Column(
            "role",
            sa.Enum("project_manager", "member", name="initiative_role"),
            nullable=True,
        ),
    )

    # 3. Migrate role_id back to enum
    op.execute("""
        UPDATE initiative_members im
        SET role = 'project_manager'::initiative_role
        FROM initiative_roles ir
        WHERE ir.id = im.role_id
        AND ir.name = 'project_manager'
    """)
    op.execute("""
        UPDATE initiative_members im
        SET role = 'member'::initiative_role
        FROM initiative_roles ir
        WHERE ir.id = im.role_id
        AND ir.name = 'member'
    """)
    # Default any NULLs to member
    op.execute("""
        UPDATE initiative_members
        SET role = 'member'::initiative_role
        WHERE role IS NULL
    """)

    # 4. Set not null and default
    op.alter_column(
        "initiative_members",
        "role",
        nullable=False,
        server_default="member",
    )

    # 5. Drop role_id column and index
    op.drop_index("ix_initiative_members_role_id", table_name="initiative_members")
    op.drop_column("initiative_members", "role_id")

    # 6. Drop new tables
    op.drop_table("initiative_role_permissions")
    op.drop_index("ix_initiative_roles_initiative_id", table_name="initiative_roles")
    op.drop_table("initiative_roles")
