"""a deployment dates its transitions

``app_settings.transitions`` maps a transition's name (``app.core.transitions``)
to when this deployment first booted with it, so a grace period runs from the
deployment's own upgrade.

Revision ID: 20260925_0395
Revises: 20260925_0394
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260925_0395"
down_revision = "20260925_0394"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "transitions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "transitions")
