"""add post scheduling

Two instants on ``posts``: ``scheduled_for``, when the author asked for the
notice to go up, and ``published_at``, when it did. Everything that lists posts
tests the second one, so "is this live" is a column test rather than a
comparison against the clock.

Existing notices are backfilled to ``created_at``: they went up the moment they
were written, which is what posting meant before this revision. Leaving them
NULL would empty every board on upgrade.

The search generation comment is cleared so the next boot rebuilds the guild's
search triggers and re-sweeps its entries. A post that has not been published
is not indexed, and ``published_at`` joins the columns whose change re-indexes
a row — which is what makes the publication worker's stamp put the notice into
search.

That dependency is also why the downgrade drops those triggers first: once a
boot has rebuilt them, they name ``published_at``, and Postgres refuses to drop
a column a trigger depends on.

Revision ID: 20260906_0230
Revises: 20260906_0229
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260906_0230"
down_revision = "20260906_0229"
branch_labels = None
depends_on = None

#: Asks the next boot to rebuild this guild's search triggers and re-sweep its
#: entries through the registry.
_CLEAR_SEARCH_GENERATION = "COMMENT ON TABLE search_entries IS NULL"

_BACKFILL = "UPDATE posts SET published_at = created_at WHERE published_at IS NULL"
_REMAINING = "SELECT count(*) FROM posts WHERE published_at IS NULL"


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            batch_op.f("ix_posts_scheduled_for"), ["scheduled_for"], unique=False
        )
        # The publication worker's own predicate: the unpublished rows are a
        # vanishing fraction of a board, which is exactly what an index is for.
        batch_op.create_index(
            batch_op.f("ix_posts_published_at"), ["published_at"], unique=False
        )

    # FORCE ROW LEVEL SECURITY binds the table's owner, which is the role this
    # migration runs as, and the policies key on request GUCs a migration has
    # no value for. Lifted for the backfill and restored either way.
    op.execute("ALTER TABLE posts NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(sa.text(_BACKFILL))
        remaining = op.get_bind().execute(sa.text(_REMAINING)).scalar()
        if remaining:
            raise RuntimeError(f"{remaining} posts still have no published_at")
    finally:
        op.execute("ALTER TABLE posts FORCE ROW LEVEL SECURITY")

    op.execute(_CLEAR_SEARCH_GENERATION)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    # The search triggers name ``published_at`` in their WHEN clause once a boot
    # has rebuilt them from the registry, and Postgres will not drop a column a
    # trigger depends on. Dropping them here is safe: clearing the generation
    # stamp below is what asks the next boot to build them again, without it.
    op.execute("DROP TRIGGER IF EXISTS search_post_upd ON posts")
    op.execute("DROP TRIGGER IF EXISTS search_post_ins ON posts")

    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_posts_published_at"))
        batch_op.drop_index(batch_op.f("ix_posts_scheduled_for"))
        batch_op.drop_column("published_at")
        batch_op.drop_column("scheduled_for")

    # Same as the upgrade: the next boot rebuilds triggers and re-sweeps, which
    # is what takes the publication gate back out of them.
    op.execute(_CLEAR_SEARCH_GENERATION)
