"""tags: assignments become relationships

Moves the twelve ``*_tags`` junctions into ``relationships`` as ``tagged_with``
edges and drops them. Backend only and invisible to users: the tag endpoints,
pickers and payloads keep their shapes, and the outbox keeps emitting
``changed = ['tags']`` because the facet now comes from the primitive rather
than from a junction's name.

``tagged_with`` is directional — a tag is a label, so the edge describes the
thing carrying it. The tagged entity is therefore always the source and the tag
always the target, which is what makes the write rule (write on the source, read
on the target) say what tagging has always asked: edit the thing, use any of the
guild's tags.

``guild_id`` is taken from the tag rather than left to the table's trigger. The
trigger would resolve it from the source entity and get the same answer, but a
migration that states it pays one join instead of one lookup per row.

The copy reads tables that have FORCE ROW LEVEL SECURITY, which binds even the
owner the migration runs as, and the policies key on request GUCs a migration
has no value for. So each source has FORCE lifted for the copy and the destination has it lifted and restored, and the row
counts are asserted to match.

The count assertion catches a partial copy and nothing else — both sides of it
are read under the same policies, so a copy that reads zero compares zero to
zero and passes. What holds the lift itself is
``TestJunctionsMoveTheirRows`` in ``alembic/migrations_test.py``, which replays
this revision over a database that has rows in it. A fresh install has nothing
to carry over, so every test that builds from empty passes either way.

Revision ID: 20260910_0253
Revises: 20260910_0252
Create Date: 2026-09-10
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260910_0253"
down_revision = "20260910_0252"
branch_labels = None
depends_on = None


#: The junctions, as (table, entity column, entity kind, entity table). The tag
#: is the other column in every one of them, and the direction never varies, so
#: this is the whole of what differs between one and the next. Spelled out
#: rather than read from ``app.core.relationships`` — a migration states the
#: shape of the database at its own revision, and a kind renamed later must not
#: reach back and change what this one did (``migration_imports_test``).
_JUNCTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("calendar_tags", "calendar_id", "calendar", "calendars"),
    ("calendar_event_tags", "calendar_event_id", "calendar_event", "calendar_events"),
    ("counter_group_tags", "counter_group_id", "counter_group", "counter_groups"),
    ("dashboard_tags", "dashboard_id", "dashboard", "dashboards"),
    ("document_tags", "document_id", "document", "documents"),
    ("gallery_tags", "gallery_id", "gallery", "galleries"),
    ("gallery_image_tags", "gallery_image_id", "gallery_image", "gallery_images"),
    ("post_tags", "post_id", "post", "posts"),
    ("project_tags", "project_id", "project", "projects"),
    ("queue_tags", "queue_id", "queue", "queues"),
    ("queue_item_tags", "queue_item_id", "queue_item", "queue_items"),
    ("task_tags", "task_id", "task", "tasks"),
)


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


def _copy_junctions() -> None:
    """Move the twelve junctions in, asserting nothing was left behind."""
    bind = op.get_bind()
    restore_destination = _forced(bind, "relationships")
    if restore_destination:
        op.execute("ALTER TABLE relationships NO FORCE ROW LEVEL SECURITY")
    try:
        for table, entity_col, kind, _entity_table in _JUNCTIONS:
            if not bind.execute(
                sa.text("SELECT to_regclass(:t) IS NOT NULL"), {"t": table}
            ).scalar():
                continue

            # Dropped immediately after, so there is nothing to restore it on.
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            expected = bind.execute(
                sa.text(f"SELECT count(*) FROM {table}")  # noqa: S608
            ).scalar()

            op.execute(f"""
                INSERT INTO relationships (
                    source_type, source_id, target_type, target_id,
                    relationship_type, provenance, created_at, guild_id
                )
                SELECT '{kind}', j.{entity_col}, 'tag', j.tag_id,
                       'tagged_with', 'manual', j.created_at, t.guild_id
                FROM {table} j
                JOIN tags t ON t.id = j.tag_id
                ON CONFLICT DO NOTHING
            """)  # noqa: S608

            moved = bind.execute(
                sa.text(
                    "SELECT count(*) FROM relationships "
                    "WHERE relationship_type = 'tagged_with' AND source_type = :k"
                ),
                {"k": kind},
            ).scalar()
            if moved != expected:
                raise RuntimeError(
                    f"{table}: copied {moved} of {expected} rows into relationships"
                )
            op.execute(f"DROP TABLE {table}")
    finally:
        if restore_destination:
            op.execute("ALTER TABLE relationships FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _copy_junctions)


def _rebuild_junctions() -> None:
    """Rebuild the junctions from the edges, then drop those edges.

    A tag assignment is the one thing in this table that has somewhere to go
    back to, so the downgrade is total for tags and leaves every other kind of
    edge where it is.

    Structure only: each rebuilt table takes its policies and grants from
    provisioning on the next boot, rendered from the registry the revision being
    downgraded to carries — the same way it got them the first time.
    """
    bind = op.get_bind()
    restore_destination = _forced(bind, "relationships")
    if restore_destination:
        op.execute("ALTER TABLE relationships NO FORCE ROW LEVEL SECURITY")
    try:
        for table, entity_col, kind, parent_table in _JUNCTIONS:
            op.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    {entity_col} integer NOT NULL REFERENCES {parent_table}(id),
                    tag_id integer NOT NULL REFERENCES tags(id),
                    created_at timestamptz NOT NULL,
                    PRIMARY KEY ({entity_col}, tag_id)
                )
            """)  # noqa: S608
            op.execute(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_tag_id ON {table} (tag_id)"  # noqa: S608
            )
            op.execute(f"""
                INSERT INTO {table} ({entity_col}, tag_id, created_at)
                SELECT r.source_id, r.target_id, r.created_at
                FROM relationships r
                WHERE r.relationship_type = 'tagged_with'
                  AND r.source_type = '{kind}'
                  AND r.removed_at IS NULL
                ON CONFLICT DO NOTHING
            """)  # noqa: S608
        op.execute("DELETE FROM relationships WHERE relationship_type = 'tagged_with'")
    finally:
        if restore_destination:
            op.execute("ALTER TABLE relationships FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _rebuild_junctions)
