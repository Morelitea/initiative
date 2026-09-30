"""the template carries structure only

Releases 0.70 and 0.71 applied the guild row security and search DDL to
``guild_template`` at every start. 0.72 stopped (the template is read for its
structure alone), but the databases those releases started kept what they
wrote: every template table with row security enabled and forced, and the
search entity-type check as those releases rendered it. A fresh install has
neither, so the two histories differ.

This brings both to one state: no template table enables or forces row
security, and the template's check names the types 0207 created it with. Each
community's own check is rendered from the registry when it is provisioned,
so no community schema is touched.

Revision ID: 20260930_0423
Revises: 20260930_0422
Create Date: 2026-09-30
"""

from alembic import op

revision = "20260930_0423"
down_revision = "20260930_0422"
branch_labels = None
depends_on = None

#: The entity types 0207 created the template's check with.
ENTITY_TYPES = (
    "calendar",
    "calendar_event",
    "counter",
    "counter_group",
    "dashboard",
    "document",
    "project",
    "queue",
    "queue_item",
    "tag",
    "task",
)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE t record;
        BEGIN
            FOR t IN
                SELECT c.relname FROM pg_class c
                 WHERE c.relnamespace = 'guild_template'::regnamespace
                   AND c.relkind IN ('r', 'p')
                   AND (c.relrowsecurity OR c.relforcerowsecurity)
            LOOP
                EXECUTE format(
                    'ALTER TABLE guild_template.%I '
                    'NO FORCE ROW LEVEL SECURITY, DISABLE ROW LEVEL SECURITY',
                    t.relname
                );
            END LOOP;
        END
        $$
        """
    )
    values = ", ".join(f"'{t}'" for t in ENTITY_TYPES)
    op.execute(
        "ALTER TABLE guild_template.search_entries "
        "DROP CONSTRAINT IF EXISTS ck_search_entries_entity_type"
    )
    op.execute(
        "ALTER TABLE guild_template.search_entries "
        "ADD CONSTRAINT ck_search_entries_entity_type "
        f"CHECK (entity_type IN ({values}))"
    )


def downgrade() -> None:
    # Which tables forced row security before, and on which history, is not
    # recorded; the state this leaves is the one both histories share.
    pass
