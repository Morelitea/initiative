"""a community may ask for help

``guild_administration.support_enabled`` says whether this community's members
can send a help request.

An operator entitlement, beside ``guild_auth_enabled`` and
``banner_image_enabled``, and off for every existing community and every new
one: the deployment that would receive the requests is the one that decides it
is staffing them. Until it does, the "Ask for help" control opens the FAQ.

No grant goes with it. Nothing on the request path writes
``guild_administration`` — the operator endpoints run on the system engine —
so the column inherits the table's existing terms.

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
        "guild_administration",
        sa.Column(
            "support_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("guild_administration", "support_enabled")
