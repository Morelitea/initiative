"""Whether this deployment offers direct messages at all.

One column, no new table and nothing to carry into one.

``app_settings.direct_messages_enabled`` -- whether My Messages exists here.
Defaults true so a deployment that upgrades keeps the messaging its people are
already using; a platform owner turns it off for somewhere messaging does not
belong.

Nothing is deleted when it goes off. Devices, keys, queued ciphertext, every policy
and every accepted channel stay exactly as they are, so turning it back on
restores what was there rather than asking everyone to rebuild it.

``app_settings`` is granted table-wide to the owner tier, so the new column
arrives writable, and no policy references it -- an ``ADD COLUMN`` is not a
policy-bound write, so there is no RLS to lift.

Revision ID: 20260916_0288
Revises: 20260916_0287
Create Date: 2026-09-16
"""

import sqlalchemy as sa
from alembic import op

revision = "20260916_0288"
down_revision = "20260916_0287"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "direct_messages_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "direct_messages_enabled")
