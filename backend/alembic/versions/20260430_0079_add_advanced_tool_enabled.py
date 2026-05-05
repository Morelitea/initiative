"""Add advanced_tool_enabled column to initiatives.

Per-initiative toggle for the optional advanced tool plug-in. The toggle
only surfaces in the SPA when the backend has ``ADVANCED_TOOL_URL`` set;
otherwise the column stays at its default ``false`` and is invisible.

Revision ID: 20260430_0079
Revises: 20260426_0078
Create Date: 2026-04-30
"""

import sqlalchemy as sa
from alembic import op


revision = "20260430_0079"
down_revision = "20260426_0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "initiatives",
        sa.Column(
            "advanced_tool_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("initiatives", "advanced_tool_enabled")
