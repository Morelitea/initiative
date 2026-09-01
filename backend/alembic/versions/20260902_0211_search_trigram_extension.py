"""pg_trgm, for close-match search suggestions

Whole-word matching cannot answer a misspelling: someone who types ``comunity``
gets an empty page. ``pg_trgm`` supplies ``word_similarity``, which the search
service falls back on when a query matches nothing, to offer the closest titles
instead.

It is a *trusted* extension, so the app's own least-privilege provisioning role
can create it — nothing here needs a superuser. Where it genuinely cannot be
installed the upgrade still goes through and the suggestion is simply never
offered, which is the behaviour before this migration.

Revision ID: 20260902_0211
Revises: 20260902_0210
Create Date: 2026-09-02
"""

from alembic import op

revision = "20260902_0211"
down_revision = "20260902_0210"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS pg_trgm;
        EXCEPTION
            WHEN insufficient_privilege OR feature_not_supported OR undefined_file THEN
                RAISE NOTICE
                    'pg_trgm unavailable; search will not suggest close matches';
        END
        $$;
        """
    )


def downgrade() -> None:
    # Left in place: other things may have come to depend on it, and an
    # extension carrying no data of ours costs nothing to keep.
    pass
