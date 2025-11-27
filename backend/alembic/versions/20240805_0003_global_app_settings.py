"""Reintroduce global app settings and drop guild auto-approval columns.

Revision ID: 20240805_0003
Revises: 20240804_0002
Create Date: 2024-08-05 00:00:00.000000
"""

from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20240805_0003"
down_revision: Union[str, None] = "20240804_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_ROLE_LABELS = {
    "admin": "Admin",
    "project_manager": "Project manager",
    "member": "Member",
}


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("oidc_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("oidc_discovery_url", sa.String(), nullable=True),
        sa.Column("oidc_client_id", sa.String(), nullable=True),
        sa.Column("oidc_client_secret", sa.String(), nullable=True),
        sa.Column("oidc_provider_name", sa.String(), nullable=True),
        sa.Column(
            "oidc_scopes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text('\'["openid","profile","email"]\'::jsonb'),
        ),
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
        sa.Column("smtp_secure", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "smtp_reject_unauthorized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("smtp_username", sa.String(length=255), nullable=True),
        sa.Column("smtp_password", sa.String(length=255), nullable=True),
        sa.Column("smtp_from_address", sa.String(length=255), nullable=True),
        sa.Column("smtp_test_recipient", sa.String(length=255), nullable=True),
    )

    bind = op.get_bind()
    source = bind.execute(sa.text("SELECT * FROM guild_settings ORDER BY guild_id ASC LIMIT 1")).mappings().first()
    insert_values = {
        "id": 1,
        "oidc_enabled": source["oidc_enabled"] if source else False,
        "oidc_discovery_url": source["oidc_discovery_url"] if source else None,
        "oidc_client_id": source["oidc_client_id"] if source else None,
        "oidc_client_secret": source["oidc_client_secret"] if source else None,
        "oidc_provider_name": source["oidc_provider_name"] if source else None,
        "oidc_scopes": json.dumps(source["oidc_scopes"] if source else ["openid", "profile", "email"]),
        "light_accent_color": source["light_accent_color"] if source else "#2563eb",
        "dark_accent_color": source["dark_accent_color"] if source else "#60a5fa",
        "role_labels": json.dumps(source["role_labels"] if source else DEFAULT_ROLE_LABELS),
        "smtp_host": source["smtp_host"] if source else None,
        "smtp_port": source["smtp_port"] if source else None,
        "smtp_secure": source["smtp_secure"] if source else False,
        "smtp_reject_unauthorized": source["smtp_reject_unauthorized"] if source else True,
        "smtp_username": source["smtp_username"] if source else None,
        "smtp_password": source["smtp_password"] if source else None,
        "smtp_from_address": source["smtp_from_address"] if source else None,
        "smtp_test_recipient": source["smtp_test_recipient"] if source else None,
    }
    bind.execute(sa.text(
        """
        INSERT INTO app_settings (
            id,
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
        ) VALUES (
            :id,
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
    ), insert_values)

    columns_to_drop = [
        "auto_approved_domains",
        "oidc_enabled",
        "oidc_discovery_url",
        "oidc_client_id",
        "oidc_client_secret",
        "oidc_provider_name",
        "oidc_scopes",
        "light_accent_color",
        "dark_accent_color",
        "role_labels",
        "smtp_host",
        "smtp_port",
        "smtp_secure",
        "smtp_reject_unauthorized",
        "smtp_username",
        "smtp_password",
        "smtp_from_address",
        "smtp_test_recipient",
    ]

    with op.batch_alter_table("guild_settings") as batch:
        for column in columns_to_drop:
            batch.drop_column(column)

    op.add_column(
        "guild_settings",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("TIMEZONE('utc', NOW())"),
            nullable=False,
        ),
    )
    op.add_column(
        "guild_settings",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("TIMEZONE('utc', NOW())"),
            nullable=False,
        ),
    )

    op.execute(
        sa.text(
            """
            UPDATE guild_settings
            SET created_at = COALESCE(created_at, TIMEZONE('utc', NOW())),
                updated_at = COALESCE(updated_at, TIMEZONE('utc', NOW()))
            """
        )
    )

    with op.batch_alter_table("guild_settings") as batch:
        batch.alter_column("created_at", server_default=None)
        batch.alter_column("updated_at", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("guild_settings") as batch:
        batch.add_column(sa.Column("smtp_test_recipient", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("smtp_from_address", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("smtp_password", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("smtp_username", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("smtp_reject_unauthorized", sa.Boolean(), nullable=False, server_default=sa.text("true")))
        batch.add_column(sa.Column("smtp_secure", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch.add_column(sa.Column("smtp_port", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("smtp_host", sa.String(length=255), nullable=True))
        batch.add_column(
            sa.Column(
                "role_labels",
                sa.JSON(),
                nullable=False,
                server_default=sa.text(f"'{json.dumps(DEFAULT_ROLE_LABELS)}'::jsonb"),
            )
        )
        batch.add_column(sa.Column("dark_accent_color", sa.String(length=20), nullable=False, server_default="#60a5fa"))
        batch.add_column(sa.Column("light_accent_color", sa.String(length=20), nullable=False, server_default="#2563eb"))
        batch.add_column(
            sa.Column(
                "oidc_scopes",
                sa.JSON(),
                nullable=False,
                server_default=sa.text('\'["openid","profile","email"]\'::jsonb'),
            )
        )
        batch.add_column(sa.Column("oidc_provider_name", sa.String(), nullable=True))
        batch.add_column(sa.Column("oidc_client_secret", sa.String(), nullable=True))
        batch.add_column(sa.Column("oidc_client_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("oidc_discovery_url", sa.String(), nullable=True))
        batch.add_column(sa.Column("oidc_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch.add_column(sa.Column("auto_approved_domains", sa.JSON(), nullable=False, server_default="[]"))

    op.drop_column("guild_settings", "updated_at")
    op.drop_column("guild_settings", "created_at")
    op.drop_table("app_settings")
