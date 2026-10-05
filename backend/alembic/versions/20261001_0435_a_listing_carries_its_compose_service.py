"""A listing carries its Compose service

A container app's listing may carry the Compose service its publisher wrote,
which the settings page shows filled in for the operator to copy. It is an app
fact, kept on the registration beside the image. Nothing is written: the
apply of a listing fills it.

Revision ID: 20261001_0435
Revises: 20261001_0434
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261001_0435"
down_revision = "20261001_0434"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_service_registrations",
        sa.Column("compose", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_service_registrations", "compose")
