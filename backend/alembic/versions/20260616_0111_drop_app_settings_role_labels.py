"""Drop the platform-wide app_settings.role_labels column.

The branding "role labels" setting (a single global rename of Admin / Project
manager / Member) is removed in favour of per-initiative role display names, which
already exist (``initiative_roles.display_name``). This drops the now-unused column.

Revision ID: 20260616_0111
Revises: 20260616_0110
Create Date: 2026-06-16
"""

import sqlalchemy as sa
from alembic import op

revision = "20260616_0111"
down_revision = "20260616_0110"
branch_labels = None
depends_on = None

_DEFAULT_ROLE_LABELS = (
    '{"admin": "Admin", "member": "Member", "project_manager": "Project manager"}'
)


def upgrade() -> None:
    op.drop_column("app_settings", "role_labels")


def downgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "role_labels",
            sa.JSON(),
            nullable=False,
            server_default=_DEFAULT_ROLE_LABELS,
        ),
    )
