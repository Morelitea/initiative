"""members share to the marketplace

A deployment's marketplace takes ``local`` listings: items its members share
from their communities, and listing files its owner uploads. Three columns:

* ``marketplace_listings.submitted_by`` — the member who shared a listing, the
  one account that may publish a new version of it or take it down. Set NULL
  when that account is gone; the listing stays.
* ``marketplace_listing_versions.awaiting_review`` — a shared version stored
  but not yet offered. Every version published so far was offered, so the
  default is false.
* ``app_settings.marketplace_members_publish_directly`` — whether a share skips
  the review. Off.

The catalog tables' grants are table-wide and the settings row's are too, so
no grant changes.

Revision ID: 20260923_0372
Revises: 20260923_0371
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0372"
down_revision = "20260923_0371"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace_listings",
        sa.Column("submitted_by", sa.Integer(), nullable=True),
        schema="public",
    )
    op.create_foreign_key(
        "marketplace_listings_submitted_by_fkey",
        "marketplace_listings",
        "users",
        ["submitted_by"],
        ["id"],
        source_schema="public",
        referent_schema="public",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_marketplace_listings_submitted_by",
        "marketplace_listings",
        ["submitted_by"],
        schema="public",
    )
    op.add_column(
        "marketplace_listing_versions",
        sa.Column(
            "awaiting_review",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        schema="public",
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "marketplace_members_publish_directly",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        schema="public",
    )


def downgrade() -> None:
    # The previous build has no ``local`` source to name these by. Their
    # versions go with them (ON DELETE CASCADE).
    op.execute("ALTER TABLE public.marketplace_listings NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute("DELETE FROM public.marketplace_listings WHERE source = 'local'")
    finally:
        op.execute("ALTER TABLE public.marketplace_listings FORCE ROW LEVEL SECURITY")
    op.drop_column(
        "app_settings", "marketplace_members_publish_directly", schema="public"
    )
    op.drop_column("marketplace_listing_versions", "awaiting_review", schema="public")
    op.drop_index(
        "ix_marketplace_listings_submitted_by",
        table_name="marketplace_listings",
        schema="public",
    )
    op.drop_constraint(
        "marketplace_listings_submitted_by_fkey",
        "marketplace_listings",
        schema="public",
        type_="foreignkey",
    )
    op.drop_column("marketplace_listings", "submitted_by", schema="public")
