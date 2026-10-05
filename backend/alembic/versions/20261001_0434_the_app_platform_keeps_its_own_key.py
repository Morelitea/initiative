"""The app platform keeps its own key

A deployment with no ``APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM`` now generates the
key it signs app tokens with on first start, and keeps it here, encrypted like
the credentials beside it. Nothing is written: the first start fills it.

Revision ID: 20261001_0434
Revises: 20261001_0433
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0434"
down_revision = "20261001_0433"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_setting_secrets",
        sa.Column(
            "app_platform_signing_key_encrypted",
            sa.String(length=4000),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("app_setting_secrets", "app_platform_signing_key_encrypted")
