"""a hold runs out

Adds ``app_settings.on_hold_community_deletion_days``: how long a community
stays on hold before the purge worker deletes it. Deleted, not destroyed — the
community then waits out ``deleted_community_retention_days`` like any other.

Nullable, and NULL means never: a held community waits for somebody to lift the
hold or delete it. The default is 30 on a fresh install and on every upgrade.

Revision ID: 20260924_0373
Revises: 20260923_0372
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260924_0373"
down_revision = "20260923_0372"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "on_hold_community_deletion_days",
            sa.Integer(),
            nullable=True,
            server_default="30",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "on_hold_community_deletion_days")
