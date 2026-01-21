"""Add AI settings to app_settings, guild_settings, and users

Revision ID: 20260120_0021
Revises: 20260116_0020
Create Date: 2026-01-20

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260120_0021"
down_revision: Union[str, None] = "20260116_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add AI settings to app_settings table
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(
            sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false"))
        )
        batch.add_column(sa.Column("ai_provider", sa.String(50), nullable=True))
        batch.add_column(sa.Column("ai_api_key", sa.String(500), nullable=True))
        batch.add_column(sa.Column("ai_base_url", sa.String(500), nullable=True))
        batch.add_column(sa.Column("ai_model", sa.String(100), nullable=True))
        batch.add_column(
            sa.Column(
                "ai_allow_guild_override", sa.Boolean(), nullable=False, server_default=sa.text("true")
            )
        )
        batch.add_column(
            sa.Column(
                "ai_allow_user_override", sa.Boolean(), nullable=False, server_default=sa.text("true")
            )
        )

    # Add AI settings to guild_settings table
    with op.batch_alter_table("guild_settings") as batch:
        batch.add_column(sa.Column("ai_enabled", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("ai_provider", sa.String(50), nullable=True))
        batch.add_column(sa.Column("ai_api_key", sa.String(500), nullable=True))
        batch.add_column(sa.Column("ai_base_url", sa.String(500), nullable=True))
        batch.add_column(sa.Column("ai_model", sa.String(100), nullable=True))
        batch.add_column(sa.Column("ai_allow_user_override", sa.Boolean(), nullable=True))

    # Add AI settings to users table
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("ai_enabled", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("ai_provider", sa.String(50), nullable=True))
        batch.add_column(sa.Column("ai_api_key", sa.String(500), nullable=True))
        batch.add_column(sa.Column("ai_base_url", sa.String(500), nullable=True))
        batch.add_column(sa.Column("ai_model", sa.String(100), nullable=True))


def downgrade() -> None:
    # Remove AI settings from users table
    with op.batch_alter_table("users") as batch:
        batch.drop_column("ai_model")
        batch.drop_column("ai_base_url")
        batch.drop_column("ai_api_key")
        batch.drop_column("ai_provider")
        batch.drop_column("ai_enabled")

    # Remove AI settings from guild_settings table
    with op.batch_alter_table("guild_settings") as batch:
        batch.drop_column("ai_allow_user_override")
        batch.drop_column("ai_model")
        batch.drop_column("ai_base_url")
        batch.drop_column("ai_api_key")
        batch.drop_column("ai_provider")
        batch.drop_column("ai_enabled")

    # Remove AI settings from app_settings table
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("ai_allow_user_override")
        batch.drop_column("ai_allow_guild_override")
        batch.drop_column("ai_model")
        batch.drop_column("ai_base_url")
        batch.drop_column("ai_api_key")
        batch.drop_column("ai_provider")
        batch.drop_column("ai_enabled")
