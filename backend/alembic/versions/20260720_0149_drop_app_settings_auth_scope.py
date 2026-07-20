"""Drop ``app_settings.auth_scope`` — posture is now a deploy-time config value.

Login posture (platform vs guild) moves from a mutable ``app_settings`` column
to the deploy-time ``AUTH_SCOPE`` env value (``app.core.config``). The column and
its runtime setter are removed; nothing reads it anymore.

Downgrade restores the column with its original ``'platform'`` server default so
an older build's reads keep working.

Revision ID: 20260720_0149
Revises: 20260718_0148
Create Date: 2026-07-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260720_0149"
down_revision = "20260718_0148"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("app_settings", "auth_scope")


def downgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "auth_scope",
            sa.String(length=20),
            nullable=False,
            server_default="platform",
        ),
    )
