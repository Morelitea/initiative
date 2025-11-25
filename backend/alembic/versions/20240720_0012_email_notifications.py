"""Add SMTP and notification infrastructure.

Revision ID: 20240720_0012
Revises: 20240717_0011
Create Date: 2024-07-20 00:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20240720_0012"
down_revision: Union[str, None] = "20240717_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("smtp_host", sa.String(length=255), nullable=True))
    op.add_column("app_settings", sa.Column("smtp_port", sa.Integer(), nullable=True))
    op.add_column(
        "app_settings",
        sa.Column("smtp_secure", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "smtp_reject_unauthorized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column("app_settings", sa.Column("smtp_username", sa.String(length=255), nullable=True))
    op.add_column("app_settings", sa.Column("smtp_password", sa.String(length=255), nullable=True))
    op.add_column("app_settings", sa.Column("smtp_from_address", sa.String(length=255), nullable=True))
    op.add_column("app_settings", sa.Column("smtp_test_recipient", sa.String(length=255), nullable=True))

    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "users",
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
    )
    op.add_column(
        "users",
        sa.Column(
            "overdue_notification_time",
            sa.String(length=5),
            nullable=False,
            server_default="21:00",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notify_initiative_addition",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notify_task_assignment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notify_project_added",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notify_overdue_tasks",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_overdue_notification_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_task_assignment_digest_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_token_purpose') THEN
                CREATE TYPE user_token_purpose AS ENUM ('email_verification', 'password_reset');
            END IF;
        END$$;
        """
    )
    user_token_enum_for_column = postgresql.ENUM(
        "email_verification",
        "password_reset",
        name="user_token_purpose",
        create_type=False,
    )

    op.create_table(
        "user_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("purpose", user_token_enum_for_column, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_tokens_token"), "user_tokens", ["token"], unique=True)
    op.create_index(op.f("ix_user_tokens_user_id"), "user_tokens", ["user_id"], unique=False)

    op.create_table(
        "task_assignment_digest_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("task_title", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("assigned_by_name", sa.String(length=255), nullable=False),
        sa.Column("assigned_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_task_assignment_digest_items_user_id"),
        "task_assignment_digest_items",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_task_assignment_digest_items_user_id"), table_name="task_assignment_digest_items")
    op.drop_table("task_assignment_digest_items")

    op.drop_index(op.f("ix_user_tokens_user_id"), table_name="user_tokens")
    op.drop_index(op.f("ix_user_tokens_token"), table_name="user_tokens")
    op.drop_table("user_tokens")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_token_purpose') THEN
                DROP TYPE user_token_purpose;
            END IF;
        END$$;
        """
    )

    op.drop_column("users", "last_task_assignment_digest_at")
    op.drop_column("users", "last_overdue_notification_at")
    op.drop_column("users", "notify_overdue_tasks")
    op.drop_column("users", "notify_project_added")
    op.drop_column("users", "notify_task_assignment")
    op.drop_column("users", "notify_initiative_addition")
    op.drop_column("users", "overdue_notification_time")
    op.drop_column("users", "timezone")
    op.drop_column("users", "email_verified")

    op.drop_column("app_settings", "smtp_test_recipient")
    op.drop_column("app_settings", "smtp_from_address")
    op.drop_column("app_settings", "smtp_password")
    op.drop_column("app_settings", "smtp_username")
    op.drop_column("app_settings", "smtp_reject_unauthorized")
    op.drop_column("app_settings", "smtp_secure")
    op.drop_column("app_settings", "smtp_port")
    op.drop_column("app_settings", "smtp_host")
