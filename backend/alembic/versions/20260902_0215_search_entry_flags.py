"""search entry flags

Adds the two columns a picker narrows on: whether the source row is archived,
and whether it is a template rather than an instance of one.

Both are filled here rather than left to the reindex sweep. The sweep is what
keeps them true from now on — it rewrites entries through the same function the
refresh triggers use, and the changed generation marker asks it to — but it runs
at boot, after the app is already answering queries. Filling the columns in the
same transaction that adds them means no request ever reads a template that does
not know it is one.

``search_entries`` forces row-level security, and a migration has no request
context for its policies to read, so the write is bracketed by lifting and
restoring that. A failure anywhere in between rolls the whole migration back,
restoring it with everything else.

Revision ID: 20260902_0215
Revises: 20260902_0214
Create Date: 2026-09-02
"""

from alembic import op

from app.db.guild_migrations import apply_to_all_guild_schemas

revision = "20260902_0215"
down_revision = "20260902_0214"
branch_labels = None
depends_on = None


ADD_COLUMNS = """
ALTER TABLE search_entries
    ADD COLUMN archived boolean NOT NULL DEFAULT false,
    ADD COLUMN template boolean NOT NULL DEFAULT false
"""

DROP_COLUMNS = """
ALTER TABLE search_entries
    DROP COLUMN archived,
    DROP COLUMN template
"""

#: The three source tables carrying either flag, as they stand today, bracketed
#: by lifting and restoring the table's forced row-level security. A snapshot on
#: purpose: a migration records what was done, and the registry that renders the
#: triggers is what keeps saying it afterwards.
BACKFILL = (
    "ALTER TABLE search_entries NO FORCE ROW LEVEL SECURITY",
    """
    UPDATE search_entries e
       SET archived = p.is_archived, template = p.is_template
      FROM projects p
     WHERE e.entity_type = 'project' AND e.entity_id = p.id
    """,
    """
    UPDATE search_entries e
       SET archived = t.is_archived
      FROM tasks t
     WHERE e.entity_type = 'task' AND e.entity_id = t.id
    """,
    """
    UPDATE search_entries e
       SET template = d.is_template
      FROM documents d
     WHERE e.entity_type = 'document' AND e.entity_id = d.id
    """,
    "ALTER TABLE search_entries FORCE ROW LEVEL SECURITY",
)

#: Asks the next boot to rewrite this guild's entries through the registry, so
#: the columns above go on being derived rather than staying as written here.
CLEAR_GENERATION = "COMMENT ON TABLE search_entries IS NULL"


def upgrade() -> None:
    apply_to_all_guild_schemas(op.get_bind(), ADD_COLUMNS)
    apply_to_all_guild_schemas(op.get_bind(), *BACKFILL)
    apply_to_all_guild_schemas(op.get_bind(), CLEAR_GENERATION)


def downgrade() -> None:
    apply_to_all_guild_schemas(op.get_bind(), DROP_COLUMNS)
    apply_to_all_guild_schemas(op.get_bind(), CLEAR_GENERATION)
