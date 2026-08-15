"""Mark a dashboard listing an app ships with itself.

An app that declares widgets otherwise leaves every guild to arrange them. A
publisher can now ship ready-made arrangements in the manifest, and publishing
the app derives one ordinary ``dashboard`` listing per entry.

They are ordinary in every respect a guild can see — same kind, same uid rules,
installed by the same call — because a dashboard published to share and one that
arrives with an app are the same thing to whoever installs it. This column
carries the two ways they differ: such a listing is offered only to guilds that
have the app installed, and it is published and withdrawn with the app rather
than on its own.

Nullable with no backfill: every existing listing was published on its own,
which is exactly what NULL means.

Revision ID: 20260815_0182
Revises: 20260814_0181
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260815_0182"
down_revision = "20260814_0181"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace_listings",
        sa.Column("bundled_with_uid", sa.String(length=14), nullable=True),
        schema="public",
    )
    # The read this exists for runs on every catalog browse inside a guild:
    # "which of these are bundled, and with what".
    op.create_index(
        "ix_marketplace_listings_bundled_with_uid",
        "marketplace_listings",
        ["bundled_with_uid"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketplace_listings_bundled_with_uid",
        table_name="marketplace_listings",
        schema="public",
    )
    op.drop_column("marketplace_listings", "bundled_with_uid", schema="public")
