"""a community may ask for help

``guilds.support_enabled`` says whether this community's members can send a
help request to whoever runs the deployment.

Off for every existing community and for every new one. A self-hosted install
has nobody staffing a queue, so the "Ask for help" affordance shows the FAQ
until an admin turns this on.

Revision ID: 20260915_0275
Revises: 20260915_0274
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260915_0275"
down_revision = "20260915_0274"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guilds",
        sa.Column(
            "support_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # 0138 pinned the guild-admin write path on ``public.guilds`` to a literal
    # column list, so every column added since names itself — as 0203 did for
    # show_member_names. This is one a guild's own admin sets, from the
    # community's settings.
    op.execute(
        "GRANT UPDATE (support_enabled) ON TABLE public.guilds TO app_guild_base"
    )


def downgrade() -> None:
    op.drop_column("guilds", "support_enabled")
