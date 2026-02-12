"""Rename oidc_discovery_url to oidc_issuer

Revision ID: 20260212_0050
Revises: 20260211_0049
Create Date: 2026-02-12
"""

from alembic import op

revision = "20260212_0050"
down_revision = "20260211_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("app_settings", "oidc_discovery_url", new_column_name="oidc_issuer")


def downgrade() -> None:
    op.alter_column("app_settings", "oidc_issuer", new_column_name="oidc_discovery_url")
