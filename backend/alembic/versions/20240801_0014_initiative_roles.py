"""Add initiative roles and default initiative.

Revision ID: 20240801_0014
Revises: 20240721_0013
Create Date: 2024-08-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20240801_0014"
down_revision: Union[str, None] = "20240721_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_INITIATIVE_NAME = "Default Initiative"
DEFAULT_INITIATIVE_COLOR = "#2563eb"


def _update_user_role_enum() -> None:
    bind = op.get_bind()
    old_enum_name = "user_role"
    tmp_enum_name = f"{old_enum_name}_old"
    op.alter_column("users", "role", server_default=None)
    op.execute(sa.text(f"ALTER TYPE {old_enum_name} RENAME TO {tmp_enum_name}"))

    new_enum = postgresql.ENUM("admin", "member", name=old_enum_name)
    new_enum.create(bind, checkfirst=False)

    op.alter_column(
        "users",
        "role",
        type_=new_enum,
        existing_nullable=False,
        postgresql_using=f"role::text::{old_enum_name}",
    )
    op.alter_column("users", "role", server_default=sa.text("'member'::user_role"))
    op.execute(sa.text(f"DROP TYPE {tmp_enum_name}"))


def _downgrade_user_role_enum() -> None:
    bind = op.get_bind()
    old_enum_name = "user_role"
    tmp_enum_name = f"{old_enum_name}_old"
    op.alter_column("users", "role", server_default=None)
    op.execute(sa.text(f"ALTER TYPE {old_enum_name} RENAME TO {tmp_enum_name}"))

    new_enum = postgresql.ENUM("admin", "project_manager", "member", name=old_enum_name)
    new_enum.create(bind, checkfirst=False)

    op.alter_column(
        "users",
        "role",
        type_=new_enum,
        existing_nullable=False,
        postgresql_using=f"role::text::{old_enum_name}",
    )
    op.alter_column("users", "role", server_default=sa.text("'member'::user_role"))
    op.execute(sa.text(f"DROP TYPE {tmp_enum_name}"))


def _ensure_default_initiative(bind) -> int | None:
    result = bind.execute(sa.text("SELECT id FROM initiatives WHERE is_default = true LIMIT 1"))
    initiative_id = result.scalar()
    if initiative_id:
        return initiative_id
    named_result = bind.execute(
        sa.text("SELECT id FROM initiatives WHERE name = :name LIMIT 1"),
        {"name": DEFAULT_INITIATIVE_NAME},
    )
    initiative_id = named_result.scalar()
    if initiative_id:
        bind.execute(
            sa.text("UPDATE initiatives SET is_default = true WHERE id = :id"),
            {"id": initiative_id},
        )
        return initiative_id
    insert_stmt = sa.text(
        """
        INSERT INTO initiatives (name, description, color, created_at, updated_at, is_default)
        VALUES (:name, :description, :color, TIMEZONE('utc', NOW()), TIMEZONE('utc', NOW()), true)
        RETURNING id
        """
    )
    result = bind.execute(
        insert_stmt,
        {
            "name": DEFAULT_INITIATIVE_NAME,
            "description": "Automatically created default initiative",
            "color": DEFAULT_INITIATIVE_COLOR,
        },
    )
    return result.scalar()


def upgrade() -> None:
    bind = op.get_bind()

    _update_user_role_enum()

    initiative_role = postgresql.ENUM("project_manager", "member", name="initiative_role")
    initiative_role.create(bind, checkfirst=True)

    op.add_column(
        "initiative_members",
        sa.Column("role", initiative_role, nullable=False, server_default=sa.text("'member'::initiative_role")),
    )

    op.add_column(
        "initiatives",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.alter_column("initiatives", "is_default", server_default=None)

    op.execute(
        """
        WITH ranked AS (
            SELECT initiative_id,
                   user_id,
                   ROW_NUMBER() OVER (PARTITION BY initiative_id ORDER BY joined_at) AS rn
            FROM initiative_members
        )
        UPDATE initiative_members AS im
        SET role = CASE
            WHEN ranked.rn = 1 THEN 'project_manager'::initiative_role
            ELSE 'member'::initiative_role
        END
        FROM ranked
        WHERE im.initiative_id = ranked.initiative_id
          AND im.user_id = ranked.user_id
        """
    )

    admin_result = bind.execute(sa.text("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"))
    admin_id = admin_result.scalar()
    fallback_user_result = bind.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1"))
    fallback_user_id = fallback_user_result.scalar()

    default_initiative_id = _ensure_default_initiative(bind)

    owner_id = admin_id or fallback_user_id
    if default_initiative_id:
        if owner_id:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO initiative_members (initiative_id, user_id, joined_at, role)
                    VALUES (:initiative_id, :user_id, TIMEZONE('utc', NOW()), 'project_manager')
                    ON CONFLICT (initiative_id, user_id)
                    DO UPDATE SET role = EXCLUDED.role
                    """
                ),
                {"initiative_id": default_initiative_id, "user_id": owner_id},
            )
        bind.execute(
            sa.text("UPDATE projects SET initiative_id = COALESCE(initiative_id, :default_id)"),
            {"default_id": default_initiative_id},
        )

    op.alter_column("projects", "initiative_id", existing_type=sa.Integer(), nullable=False)

    op.create_index(
        "uq_initiatives_default",
        "initiatives",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    # Project permission overhaul
    op.drop_column("projects", "read_roles")
    op.drop_column("projects", "write_roles")

    op.rename_table("project_members", "project_permissions")

    op.alter_column(
        "project_permissions",
        "joined_at",
        new_column_name="created_at",
        existing_type=sa.DateTime(timezone=True),
    )
    permission_level_enum = postgresql.ENUM("owner", "write", name="project_permission_level")
    permission_level_enum.create(bind, checkfirst=True)

    op.add_column(
        "project_permissions",
        sa.Column(
            "level",
            permission_level_enum,
            nullable=False,
            server_default=sa.text("'write'::project_permission_level"),
        ),
    )

    op.execute(
        """
        UPDATE project_permissions AS pp
        SET level = CASE
            WHEN projects.owner_id = pp.user_id THEN 'owner'::project_permission_level
            ELSE 'write'::project_permission_level
        END
        FROM projects
        WHERE pp.project_id = projects.id
        """
    )

    op.alter_column("project_permissions", "level", server_default=None)

    op.drop_column("project_permissions", "role")
    op.execute(sa.text("DROP TYPE IF EXISTS project_role CASCADE"))

    op.execute(
        """
        INSERT INTO project_permissions (project_id, user_id, level, created_at)
        SELECT
            projects.id,
            projects.owner_id,
            'owner'::project_permission_level,
            COALESCE(projects.created_at, TIMEZONE('utc', NOW()))
        FROM projects
        WHERE NOT EXISTS (
            SELECT 1
            FROM project_permissions
            WHERE project_permissions.project_id = projects.id
              AND project_permissions.user_id = projects.owner_id
        )
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("uq_initiatives_default", table_name="initiatives")
    op.alter_column("projects", "initiative_id", existing_type=sa.Integer(), nullable=True)

    # Recreate dropped project columns
    op.add_column(
        "projects",
        sa.Column(
            "read_roles",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"admin\", \"project_manager\", \"member\"]'::jsonb"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "write_roles",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"admin\", \"project_manager\"]'::jsonb"),
        ),
    )

    # Revert project permissions table
    project_role_enum = postgresql.ENUM("admin", "project_manager", "member", name="project_role")
    project_role_enum.create(bind, checkfirst=True)

    op.add_column(
        "project_permissions",
        sa.Column(
            "role",
            project_role_enum,
            nullable=False,
            server_default=sa.text("'member'::project_role"),
        ),
    )

    op.execute(
        """
        UPDATE project_permissions
        SET role = CASE
            WHEN level = 'owner' THEN 'admin'
            ELSE 'project_manager'
        END
        """
    )

    op.drop_column("project_permissions", "level")

    permission_level_enum = postgresql.ENUM("owner", "write", name="project_permission_level")
    permission_level_enum.drop(bind, checkfirst=True)

    op.alter_column(
        "project_permissions",
        "created_at",
        new_column_name="joined_at",
        existing_type=sa.DateTime(timezone=True),
    )
    op.alter_column("project_permissions", "role", server_default=None)
    op.rename_table("project_permissions", "project_members")

    op.drop_column("initiatives", "is_default")

    op.drop_column("initiative_members", "role")

    initiative_role = postgresql.ENUM("project_manager", "member", name="initiative_role")
    initiative_role.drop(bind, checkfirst=True)

    _downgrade_user_role_enum()
