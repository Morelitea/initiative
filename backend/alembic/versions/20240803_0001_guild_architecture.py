"""Introduce guild hierarchy and guild-specific settings.

Revision ID: 20240803_0001
Revises: 20240802_0015
Create Date: 2024-08-03 00:00:00.000000
"""

from datetime import datetime, timezone
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

DEFAULT_ROLE_LABELS = {
    "admin": "Admin",
    "project_manager": "Project manager",
    "member": "Member",
}

# revision identifiers, used by Alembic.
revision: str = "20240803_0001"
down_revision: Union[str, None] = "20240802_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'guild_role') THEN
                CREATE TYPE guild_role AS ENUM ('admin', 'member');
            END IF;
        END$$;
        """
    )
    guild_role_enum = postgresql.ENUM("admin", "member", name="guild_role", create_type=False)

    op.create_table(
        "guilds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon_base64", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("TIMEZONE('utc', NOW())")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("TIMEZONE('utc', NOW())")),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
    )

    op.add_column("users", sa.Column("active_guild_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_users_active_guild_id",
        "users",
        "guilds",
        ["active_guild_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "guild_memberships",
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            guild_role_enum,
            nullable=False,
            server_default="member",
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("TIMEZONE('utc', NOW())")),
        sa.PrimaryKeyConstraint("guild_id", "user_id"),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "guild_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invitee_email", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("TIMEZONE('utc', NOW())")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_guild_invites_code"), "guild_invites", ["code"], unique=True)

    op.add_column("initiatives", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_initiatives_guild_id",
        "initiatives",
        "guilds",
        ["guild_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_table(
        "guild_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("auto_approved_domains", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("oidc_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("oidc_discovery_url", sa.String(), nullable=True),
        sa.Column("oidc_client_id", sa.String(), nullable=True),
        sa.Column("oidc_client_secret", sa.String(), nullable=True),
        sa.Column("oidc_provider_name", sa.String(), nullable=True),
        sa.Column("oidc_scopes", sa.JSON(), nullable=False, server_default='["openid","profile","email"]'),
        sa.Column("light_accent_color", sa.String(length=20), nullable=False, server_default="#2563eb"),
        sa.Column("dark_accent_color", sa.String(length=20), nullable=False, server_default="#60a5fa"),
        sa.Column(
            "role_labels",
            sa.JSON(),
            nullable=False,
            server_default=sa.text(f"'{json.dumps(DEFAULT_ROLE_LABELS)}'::jsonb"),
        ),
        sa.Column("smtp_host", sa.String(length=255), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=True),
        sa.Column("smtp_secure", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("smtp_reject_unauthorized", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("smtp_username", sa.String(length=255), nullable=True),
        sa.Column("smtp_password", sa.String(length=255), nullable=True),
        sa.Column("smtp_from_address", sa.String(length=255), nullable=True),
        sa.Column("smtp_test_recipient", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
    )

    # Seed a primary guild and migrate existing data.
    result = bind.execute(
        sa.text(
            """
            INSERT INTO guilds (name, description, created_at, updated_at)
            VALUES (:name, :description, TIMEZONE('utc', NOW()), TIMEZONE('utc', NOW()))
            RETURNING id
            """
        ),
        {"name": "Primary Guild", "description": "Migrated default guild"},
    )
    primary_guild_id = result.scalar()

    users = bind.execute(sa.text("SELECT id, role FROM users")).all()
    membership_stmt = sa.text(
        """
        INSERT INTO guild_memberships (guild_id, user_id, role, joined_at)
        VALUES (:guild_id, :user_id, :role, TIMEZONE('utc', NOW()))
        ON CONFLICT (guild_id, user_id) DO UPDATE SET role = EXCLUDED.role
        """
    )
    for user_id, role in users:
        guild_role = "admin" if role == "admin" else "member"
        bind.execute(membership_stmt, {"guild_id": primary_guild_id, "user_id": user_id, "role": guild_role})

    bind.execute(
        sa.text("UPDATE users SET active_guild_id = :guild_id"),
        {"guild_id": primary_guild_id},
    )
    bind.execute(
        sa.text("UPDATE initiatives SET guild_id = :guild_id"),
        {"guild_id": primary_guild_id},
    )

    app_settings_row = bind.execute(sa.text("SELECT * FROM app_settings LIMIT 1")).mappings().first()
    if app_settings_row:
        insert_settings = sa.text(
            """
            INSERT INTO guild_settings (
                guild_id,
                auto_approved_domains,
                oidc_enabled,
                oidc_discovery_url,
                oidc_client_id,
                oidc_client_secret,
                oidc_provider_name,
                oidc_scopes,
                light_accent_color,
                dark_accent_color,
                role_labels,
                smtp_host,
                smtp_port,
                smtp_secure,
                smtp_reject_unauthorized,
                smtp_username,
                smtp_password,
                smtp_from_address,
                smtp_test_recipient
            )
            VALUES (
                :guild_id,
                :auto_approved_domains,
                :oidc_enabled,
                :oidc_discovery_url,
                :oidc_client_id,
                :oidc_client_secret,
                :oidc_provider_name,
                :oidc_scopes,
                :light_accent_color,
                :dark_accent_color,
                :role_labels,
                :smtp_host,
                :smtp_port,
                :smtp_secure,
                :smtp_reject_unauthorized,
                :smtp_username,
                :smtp_password,
                :smtp_from_address,
                :smtp_test_recipient
            )
            """
        )
        bind.execute(
            insert_settings,
            {
                "guild_id": primary_guild_id,
                "auto_approved_domains": app_settings_row["auto_approved_domains"],
                "oidc_enabled": app_settings_row["oidc_enabled"],
                "oidc_discovery_url": app_settings_row["oidc_discovery_url"],
                "oidc_client_id": app_settings_row["oidc_client_id"],
                "oidc_client_secret": app_settings_row["oidc_client_secret"],
                "oidc_provider_name": app_settings_row["oidc_provider_name"],
                "oidc_scopes": app_settings_row["oidc_scopes"],
                "light_accent_color": app_settings_row["light_accent_color"],
                "dark_accent_color": app_settings_row["dark_accent_color"],
                "role_labels": app_settings_row["role_labels"],
                "smtp_host": app_settings_row["smtp_host"],
                "smtp_port": app_settings_row["smtp_port"],
                "smtp_secure": app_settings_row["smtp_secure"],
                "smtp_reject_unauthorized": app_settings_row["smtp_reject_unauthorized"],
                "smtp_username": app_settings_row["smtp_username"],
                "smtp_password": app_settings_row["smtp_password"],
                "smtp_from_address": app_settings_row["smtp_from_address"],
                "smtp_test_recipient": app_settings_row["smtp_test_recipient"],
            },
        )

    op.drop_table("app_settings")

    op.alter_column("initiatives", "guild_id", nullable=False)

    op.drop_index("uq_initiatives_default", table_name="initiatives")
    op.create_index(
        "uq_initiatives_guild_default",
        "initiatives",
        ["guild_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'initiatives_name_key'
            ) THEN
                ALTER TABLE initiatives DROP CONSTRAINT initiatives_name_key;
            END IF;
        END$$;
        """
    )
    with op.batch_alter_table("initiatives") as batch:
        batch.drop_index("ix_initiatives_name")
        batch.create_index("ix_initiatives_name", ["name"], unique=False)
    op.execute("CREATE UNIQUE INDEX uq_initiatives_guild_name ON initiatives (guild_id, lower(name))")


def downgrade() -> None:
    bind = op.get_bind()

    op.execute("DROP INDEX IF EXISTS uq_initiatives_guild_name")
    with op.batch_alter_table("initiatives") as batch:
        batch.drop_index("ix_initiatives_name")
        batch.create_index("ix_initiatives_name", ["name"], unique=False)
    op.create_unique_constraint("initiatives_name_key", "initiatives", ["name"])

    op.drop_index("uq_initiatives_guild_default", table_name="initiatives")
    op.create_index(
        "uq_initiatives_default",
        "initiatives",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.drop_constraint("fk_initiatives_guild_id", "initiatives", type_="foreignkey")
    op.drop_column("initiatives", "guild_id")

    op.drop_table("guild_settings")

    op.drop_table("guild_invites")

    op.drop_table("guild_memberships")

    op.drop_constraint("fk_users_active_guild_id", "users", type_="foreignkey")
    op.drop_column("users", "active_guild_id")

    op.drop_table("guilds")

    op.execute("DROP TYPE IF EXISTS guild_role")
