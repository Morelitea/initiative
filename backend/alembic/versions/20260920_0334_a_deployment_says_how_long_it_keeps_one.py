"""a deployment says how long it keeps one

Adds ``app_settings.deleted_community_retention_days``: how long a deleted
community is kept before the purge worker destroys it.

Nullable, and NULL means never — a deployment that has undertaken to keep what
its members put in it clears the figure and nothing is ever destroyed on a
timer. The default is 90 on a fresh install and on every upgrade, which is the
window the feature shipped with.

Revision ID: 20260920_0334
Revises: 20260920_0333
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0334"
down_revision = "20260920_0333"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "deleted_community_retention_days",
            sa.Integer(),
            nullable=True,
            server_default="90",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "deleted_community_retention_days")
