"""document links become relationships

Admits ``references`` to the vocabulary, moves ``document_links`` in under it,
and drops the junction. The table held one fact — this document's body names
that one — which is what ``references`` says about any two kinds, so the
wikilink graph stops being a documents-only feature by being kept in the general
place.

The ``ck_relationships_type`` CHECK is rewritten rather than left to the model:
provisioning reflects the live ``guild_template``, so a word the constraint does
not list is one no schema will accept however the enum reads in Python.

``provenance`` is ``content``: nobody asserted these. The save path read them
out of a body, and the same save path takes them back out when the sentence
goes. ``created_by`` carries over — the junction recorded whoever saved the
content, which is the honest attributor for what that save said.

``guild_id`` is taken from the source document rather than left to the table's
trigger. The trigger would resolve it from the same row and get the same answer,
but a migration that states it pays one join instead of one lookup per row.

The copy runs with ``FORCE ROW LEVEL SECURITY`` lifted on the junction, on the
destination and on ``documents`` — which the guild is read from — and puts it
back on the two that survive. Row counts are asserted to match.

What proves the rows actually move is ``TestJunctionsMoveTheirRows`` in
``alembic/migrations_test.py``, which replays this revision over a database that
has rows in it. A fresh install has nothing to carry over, so a test built from
empty tells you nothing either way.

Revision ID: 20260911_0255
Revises: 20260911_0254
Create Date: 2026-09-11
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260911_0255"
down_revision = "20260911_0254"
branch_labels = None
depends_on = None


def _forced(bind, table: str) -> bool:
    """Whether ``table`` currently forces RLS on its owner."""
    return bool(
        bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )


#: The vocabulary after this revision. Spelled out rather than read from
#: ``app.core.relationships`` — a migration states the shape of the database at
#: its own revision, and a word added later must not reach back and change what
#: this one wrote (``migration_imports_test``).
_TYPES_AFTER = (
    "'attached', 'depends_on', 'part_of', 'references', 'related_to', 'tagged_with'"
)
_TYPES_BEFORE = "'attached', 'depends_on', 'part_of', 'related_to', 'tagged_with'"


def _set_type_check(values: str) -> None:
    """Rewrite the vocabulary a ``relationship_type`` may hold."""
    op.execute(
        "ALTER TABLE relationships DROP CONSTRAINT IF EXISTS ck_relationships_type"
    )
    op.execute(
        "ALTER TABLE relationships ADD CONSTRAINT ck_relationships_type "
        f"CHECK (relationship_type IN ({values}))"
    )


def _copy_links() -> None:
    """Admit the new word, then move the wikilink graph in under it."""
    bind = op.get_bind()
    _set_type_check(_TYPES_AFTER)

    if not bind.execute(
        sa.text("SELECT to_regclass('document_links') IS NOT NULL")
    ).scalar():
        return

    # The destination, and the table the copy reads the guild from. Both are
    # put back as they were found.
    restore = [t for t in ("relationships", "documents") if _forced(bind, t)]
    for table in restore:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        # Dropped immediately after, so there is nothing to restore it on.
        op.execute("ALTER TABLE document_links NO FORCE ROW LEVEL SECURITY")

        # A link from a document to itself was storable here and means nothing
        # as an edge, so it is left behind rather than carried into a CHECK
        # that refuses it. Counted out of the expectation for the same reason.
        expected = bind.execute(
            sa.text(
                "SELECT count(*) FROM document_links "
                "WHERE source_document_id <> target_document_id"
            )
        ).scalar()

        op.execute("""
            INSERT INTO relationships (
                source_type, source_id, target_type, target_id,
                relationship_type, provenance, created_at, created_by, guild_id
            )
            SELECT 'document', l.source_document_id,
                   'document', l.target_document_id,
                   'references', 'content', l.created_at, l.created_by,
                   d.guild_id
            FROM document_links l
            JOIN documents d ON d.id = l.source_document_id
            WHERE l.source_document_id <> l.target_document_id
            ON CONFLICT DO NOTHING
        """)

        moved = bind.execute(
            sa.text(
                "SELECT count(*) FROM relationships "
                "WHERE relationship_type = 'references' AND provenance = 'content'"
            )
        ).scalar()
        if moved != expected:
            raise RuntimeError(
                f"document_links: copied {moved} of {expected} rows into relationships"
            )
        op.execute("DROP TABLE document_links")
    finally:
        for table in restore:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _copy_links)


def _rebuild_links() -> None:
    """Rebuild the junction from the edges, then drop those edges.

    A document-to-document reference is the one thing in this table that has
    somewhere to go back to, so the junction is rebuilt from those. A reference
    naming anything else has nowhere to go and is dropped — the next save of the
    body that made it writes it back.

    Structure only: the rebuilt table takes its policies and grants from
    provisioning on the next boot, rendered from the registry the revision being
    downgraded to carries — the same way it got them the first time.
    """
    bind = op.get_bind()
    restore_destination = _forced(bind, "relationships")
    if restore_destination:
        op.execute("ALTER TABLE relationships NO FORCE ROW LEVEL SECURITY")
    try:
        # The author stamp comes from the same shared function every other
        # guild-content table's does, so a rebuilt junction records who saved
        # the content the way the revision being returned to expects.
        op.execute("""
            CREATE TABLE IF NOT EXISTS document_links (
                source_document_id integer NOT NULL REFERENCES documents(id),
                target_document_id integer NOT NULL REFERENCES documents(id),
                guild_id integer REFERENCES guilds(id),
                created_by integer REFERENCES users(id),
                created_at timestamptz NOT NULL,
                PRIMARY KEY (source_document_id, target_document_id)
            )
        """)
        op.execute(
            "CREATE OR REPLACE TRIGGER tr_document_links_set_created_by "
            "BEFORE INSERT ON document_links "
            "FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by()"
        )
        op.execute("""
            INSERT INTO document_links (
                source_document_id, target_document_id,
                guild_id, created_by, created_at
            )
            SELECT r.source_id, r.target_id, r.guild_id, r.created_by, r.created_at
            FROM relationships r
            WHERE r.relationship_type = 'references'
              AND r.source_type = 'document'
              AND r.target_type = 'document'
              AND r.removed_at IS NULL
            ON CONFLICT DO NOTHING
        """)
        # Every remaining `references` edge goes too: the revision being
        # downgraded to has no word for one, and the save path writes them all
        # back the next time the content they came from is saved.
        op.execute("DELETE FROM relationships WHERE relationship_type = 'references'")
        _set_type_check(_TYPES_BEFORE)
    finally:
        if restore_destination:
            op.execute("ALTER TABLE relationships FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _rebuild_links)
