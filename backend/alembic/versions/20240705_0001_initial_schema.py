"""Initial schema generated for existing SQLModel tables.

Revision ID: 20240705_0001
Revises: 
Create Date: 2024-07-05 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20240705_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ENUMS: dict[str, tuple[str, ...]] = {
    "user_role": ("admin", "project_manager", "member"),
    "project_role": ("admin", "project_manager", "member"),
    "task_status": ("backlog", "in_progress", "blocked", "done"),
    "task_priority": ("low", "medium", "high", "urgent"),
}


def _create_enum_if_not_exists(name: str, values: tuple[str, ...]) -> None:
    quoted_values = ", ".join(f"'{value}'" for value in values)
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_type WHERE typname = '{name}'
                ) THEN
                    CREATE TYPE {name} AS ENUM ({quoted_values});
                END IF;
            END;
            $$;
            """
        )
    )


def upgrade() -> None:
    for enum_name, values in ENUMS.items():
        _create_enum_if_not_exists(enum_name, values)

    user_role = postgresql.ENUM(*ENUMS["user_role"], name="user_role", create_type=False)
    project_role = postgresql.ENUM(*ENUMS["project_role"], name="project_role", create_type=False)
    task_status = postgresql.ENUM(*ENUMS["task_status"], name="task_status", create_type=False)
    task_priority = postgresql.ENUM(*ENUMS["task_priority"], name="task_priority", create_type=False)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("role", user_role, nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("avatar_base64", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.String(length=2048), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)

    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_teams_name"), "teams", ["name"], unique=False)

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("icon", sa.String(length=8), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "read_roles",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"admin\", \"project_manager\", \"member\"]'::jsonb"),
        ),
        sa.Column(
            "write_roles",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"admin\", \"project_manager\"]'::jsonb"),
        ),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("is_template", sa.Boolean(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_name"), "projects", ["name"], unique=False)

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("auto_approved_domains", sa.JSON(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("oidc_enabled", sa.Boolean(), nullable=False),
        sa.Column("oidc_discovery_url", sa.String(), nullable=True),
        sa.Column("oidc_client_id", sa.String(), nullable=True),
        sa.Column("oidc_client_secret", sa.String(), nullable=True),
        sa.Column("oidc_provider_name", sa.String(), nullable=True),
        sa.Column(
            "oidc_scopes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"openid\", \"profile\", \"email\"]'::jsonb"),
        ),
        sa.Column("light_accent_color", sa.String(length=20), nullable=False, server_default=sa.text("'#2563eb'")),
        sa.Column("dark_accent_color", sa.String(length=20), nullable=False, server_default=sa.text("'#60a5fa'")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "project_members",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", project_role, nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )

    op.create_table(
        "team_members",
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("team_id", "user_id"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", task_status, nullable=False),
        sa.Column("priority", task_priority, nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "task_assignees",
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("task_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("task_assignees")
    op.drop_table("tasks")
    op.drop_table("team_members")
    op.drop_table("project_members")
    op.drop_table("app_settings")
    op.drop_index(op.f("ix_projects_name"), table_name="projects")
    op.drop_table("projects")
    op.drop_index(op.f("ix_teams_name"), table_name="teams")
    op.drop_table("teams")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    for enum_name in ("task_priority", "task_status", "project_role", "user_role"):
        op.execute(sa.text(f"DROP TYPE IF EXISTS {enum_name} CASCADE"))
