"""search entry flags

Adds the two columns a picker narrows on: whether the source row is archived,
and whether it is a template rather than an instance of one.

The columns arrive empty and are filled by the reindex sweep rather than here.
Clearing the generation marker is what asks for that sweep: the next boot sees
a guild whose marker does not match ``search_generation()`` and rewrites its
entries through the same function the refresh trigger uses, so a row written by
the backfill and a row written by a later edit are written identically.

Revision ID: 20260901_0212
Revises: 20260902_0211
Create Date: 2026-09-01
"""

from alembic import op

from app.db.guild_migrations import apply_to_all_guild_schemas

revision = "20260901_0212"
down_revision = "20260902_0211"
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

#: Asks the next boot to rewrite this guild's entries.
CLEAR_GENERATION = "COMMENT ON TABLE search_entries IS NULL"


def upgrade() -> None:
    apply_to_all_guild_schemas(op.get_bind(), ADD_COLUMNS)
    apply_to_all_guild_schemas(op.get_bind(), CLEAR_GENERATION)


def downgrade() -> None:
    apply_to_all_guild_schemas(op.get_bind(), DROP_COLUMNS)
    apply_to_all_guild_schemas(op.get_bind(), CLEAR_GENERATION)
