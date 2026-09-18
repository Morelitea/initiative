"""a wiki page already in the bin lets go of its name

Page slugs are unique per wiki, and until now a page kept its slug while it sat
in the trash: writing "Step 1" again, after throwing the first "Step 1" away,
collided with a row nobody could see, and the request failed with nothing a
reader could act on. A page now parks its slug when it is trashed and takes it
back when it is restored (``RELEASED_NAMES`` in
``app.services.tenant.soft_delete``).

This is the same for pages that went into the bin before that: their names are
parked here, so the addresses they are holding go back into circulation.

Revision ID: 20260918_0310
Revises: 20260918_0309
Create Date: 2026-09-18
"""

from alembic import op

from app.db.guild_migrations import apply_to_all_guild_schemas

revision = "20260918_0310"
down_revision = "20260918_0309"
branch_labels = None
depends_on = None


def upgrade() -> None:
    apply_to_all_guild_schemas(
        op.get_bind(),
        # Trashed rows are read-only at the database, and parking a name is a
        # write to one. This is the lifecycle escape hatch the purge path uses
        # (app.db.frozen.PURGE_GUC), set transaction-locally and put back below
        # so the rest of the upgrade runs with the guard in place.
        "SELECT set_config('app.purging', 'true', true)",
        # `~` is outside the slug alphabet, so a name that already carries one
        # has been parked and is left alone.
        """
        UPDATE wiki_pages
           SET slug = left(slug, 255 - length('~' || id::text)) || '~' || id::text
         WHERE deleted_at IS NOT NULL
           AND strpos(slug, '~') = 0
        """,
        "SELECT set_config('app.purging', 'false', true)",
    )


def downgrade() -> None:
    """Nothing to undo.

    A parked name is an ordinary slug — the old behaviour holds it against the
    wiki just as happily — and unparking would have to argue with whatever has
    taken the name since. The pages keep the addresses they have.
    """
