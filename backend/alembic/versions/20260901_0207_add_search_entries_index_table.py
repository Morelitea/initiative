"""add search_entries index table

The guild-wide search index: one row per searchable chunk of content, written
only by ``public.refresh_search_entry()`` from the tables it mirrors.

The table is created, indexed and locked down in one pass because it starts
EMPTY — there is nothing to carry in, so the create-then-backfill-then-FORCE
sequence a populated table requires does not apply here. Existing content is
indexed by the reindex sweep, not by this migration.

Revision ID: 20260901_0207
Revises: 20260831_0206
Create Date: 2026-09-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260901_0207"
down_revision = "20260831_0206"
branch_labels = None
depends_on = None

#: Entity types this migration was written with, frozen as its CHECK
#: constraint. A new searchable table extends this in its own migration, the
#: same way ``recent_views`` does.
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

#: Written by the refresh trigger; the reindex sweep routes as the guild admin.
_INSERT_CHECK = (
    "pg_trigger_depth() > 0 OR "
    "current_setting('app.current_guild_role'::text, true) = 'admin'::text"
)

#: The initiative gate, matching ``search_entries_path()`` in
#: ``app/db/initiative_rls.py``. NULL means guild-level content, where the
#: initiative gate has nothing to decide.
_UID = "(NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer"


def _access(write: bool) -> str:
    return (
        "(CASE WHEN search_entries.initiative_id IS NULL THEN true ELSE "
        f"public.initiative_access(search_entries.initiative_id, {_UID}, "
        f"{'true' if write else 'false'}) END)"
    )


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.create_table(
        "search_entries",
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column(
            "chunk_ix", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("initiative_id", sa.Integer(), nullable=True),
        sa.Column("dac_tool", sa.Text(), nullable=True),
        sa.Column("dac_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=False),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("entity_type", "entity_id", "chunk_ix"),
    )

    values = ", ".join(f"'{t}'" for t in ENTITY_TYPES)
    op.execute(
        "ALTER TABLE search_entries ADD CONSTRAINT ck_search_entries_entity_type "
        f"CHECK (entity_type IN ({values}))"
    )

    op.execute("CREATE INDEX ix_search_entries_tsv ON search_entries USING gin (tsv)")
    op.execute(
        "CREATE INDEX ix_search_entries_dac ON search_entries (dac_tool, dac_id)"
    )
    op.execute(
        "CREATE INDEX ix_search_entries_initiative ON search_entries (initiative_id)"
    )

    # Locked down at creation: the table is empty, so there is no backfill to
    # order before FORCE.
    op.execute("ALTER TABLE search_entries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE search_entries FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY initiative_member_select ON search_entries "
        f"AS PERMISSIVE FOR SELECT USING ({_access(False)})"
    )
    op.execute(
        "CREATE POLICY initiative_member_insert ON search_entries "
        f"AS PERMISSIVE FOR INSERT WITH CHECK ({_INSERT_CHECK})"
    )
    op.execute(
        "CREATE POLICY initiative_member_update ON search_entries "
        f"AS PERMISSIVE FOR UPDATE USING ({_access(True)}) "
        f"WITH CHECK ({_access(True)})"
    )
    op.execute(
        "CREATE POLICY initiative_member_delete ON search_entries "
        f"AS PERMISSIVE FOR DELETE USING ({_access(True)})"
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS initiative_member_select ON search_entries")
    op.execute("DROP POLICY IF EXISTS initiative_member_insert ON search_entries")
    op.execute("DROP POLICY IF EXISTS initiative_member_update ON search_entries")
    op.execute("DROP POLICY IF EXISTS initiative_member_delete ON search_entries")
    op.execute("ALTER TABLE search_entries DISABLE ROW LEVEL SECURITY")
    op.drop_table("search_entries")
