"""Add ``guilds.guild_auth_enabled`` — per-guild sign-in entitlement.

A per-guild operator toggle (platform Guilds dashboard) gating whether a guild
may configure its own login providers and onboard new accounts through them.
Defaults off: the operator turns it on per guild. It rides the existing
column-scoped write model on ``public.guilds`` — migration 0138 GRANTs the
guild-admin request role UPDATE on an allowlist of identity columns only, so a
guild's own admins cannot write this new column; only the operator path (system
engine) does. No policy or grant change is needed here.

Downgrade drops the column.

Revision ID: 20260720_0150
Revises: 20260720_0149
Create Date: 2026-07-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260720_0150"
down_revision = "20260720_0149"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guilds",
        sa.Column(
            "guild_auth_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("guilds", "guild_auth_enabled")
