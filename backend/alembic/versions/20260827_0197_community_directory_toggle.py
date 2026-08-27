"""add the community-directory switch to app_settings

Whether this deployment runs a community directory at all is the platform
owner's call, not a guild admin's: 0196 gave a guild the ability to list itself,
and this decides whether that listing goes anywhere. It defaults to off, so an
existing install upgrades without acquiring a browsable front door, and a guild
that had already opted in stays opted in but unlisted until an owner turns the
directory on.

It lives on ``app_settings`` — the owner-writable singleton — rather than in the
environment, so it can be flipped from the platform settings page instead of a
redeploy.

Revision ID: 20260827_0197
Revises: 20260827_0196
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision = "20260827_0197"
down_revision = "20260827_0196"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "community_directory_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "community_directory_enabled")
