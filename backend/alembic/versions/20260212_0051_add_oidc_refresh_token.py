"""Add OIDC refresh token columns and update default scopes

Revision ID: 20260212_0051
Revises: 20260212_0050
Create Date: 2026-02-12
"""

from alembic import op
import sqlalchemy as sa

revision = "20260212_0051"
down_revision = "20260212_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("oidc_refresh_token_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("oidc_last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("oidc_sub", sa.String(255), nullable=True),
    )

    # Migrate existing default scopes to include offline_access
    # Column is JSON (not JSONB), so cast both sides for comparison
    op.execute(
        """
        UPDATE app_settings
        SET oidc_scopes = '["openid", "profile", "email", "offline_access"]'::json
        WHERE oidc_scopes::jsonb = '["openid", "profile", "email"]'::jsonb
        """
    )


def downgrade() -> None:
    # Revert scopes migration
    op.execute(
        """
        UPDATE app_settings
        SET oidc_scopes = '["openid", "profile", "email"]'::json
        WHERE oidc_scopes::jsonb = '["openid", "profile", "email", "offline_access"]'::jsonb
        """
    )

    op.drop_column("users", "oidc_sub")
    op.drop_column("users", "oidc_last_synced_at")
    op.drop_column("users", "oidc_refresh_token_encrypted")
