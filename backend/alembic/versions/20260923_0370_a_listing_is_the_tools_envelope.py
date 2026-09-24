"""a listing is the tool's envelope

Every tool that exports and imports now has a marketplace, and a listing of
one is that tool's export envelope. Two changes to the catalog follow:

* ``marketplace_listing_versions.example`` — the same envelope filled in, which
  a listing may carry beside what it installs. Nullable: no listing published
  so far has one.
* Dashboard listings stored the canvas alone. Each is rewritten as the
  dashboard envelope wrapping that canvas, in exactly the shape the catalog's
  validator now produces for one (``tool_listings.normalize_tool_listing``), so
  a listing re-published at the same version still matches what is stored and
  is not refused as changed content.

Revision ID: 20260923_0370
Revises: 20260923_0369
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260923_0370"
down_revision = "20260923_0369"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace_listing_versions",
        sa.Column("example", postgresql.JSONB(), nullable=True),
        schema="public",
    )
    # The table is FORCE ROW LEVEL SECURITY and this migration carries no
    # request context, so the rewrite lifts FORCE for its own write.
    op.execute(
        "ALTER TABLE public.marketplace_listing_versions NO FORCE ROW LEVEL SECURITY"
    )
    try:
        op.execute(
            """
            UPDATE public.marketplace_listing_versions v
            SET definition = jsonb_build_object(
                'schema_version', 1,
                'type', 'initiative-dashboard',
                'name', '',
                'description', NULL,
                'definition', v.definition,
                'config', '{}'::jsonb,
                'tags', '[]'::jsonb
            )
            FROM public.marketplace_listings l
            WHERE l.id = v.listing_id
              AND l.kind = 'dashboard'
              AND NOT (v.definition ? 'type')
            """
        )
    finally:
        op.execute(
            "ALTER TABLE public.marketplace_listing_versions FORCE ROW LEVEL SECURITY"
        )


def downgrade() -> None:
    tables = ("marketplace_listing_versions", "marketplace_listings")
    for table in tables:
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            """
            UPDATE public.marketplace_listing_versions v
            SET definition = COALESCE(v.definition -> 'definition', '{}'::jsonb)
            FROM public.marketplace_listings l
            WHERE l.id = v.listing_id
              AND l.kind = 'dashboard'
              AND v.definition ? 'type'
            """
        )
        # A listing of any other tool is a kind the previous build cannot name.
        # Its versions go with it (ON DELETE CASCADE).
        op.execute(
            """
            DELETE FROM public.marketplace_listings
            WHERE kind NOT IN ('app', 'auto', 'dashboard', 'profile_pack')
            """
        )
    finally:
        for table in tables:
            op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
    op.drop_column("marketplace_listing_versions", "example", schema="public")
