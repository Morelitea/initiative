"""a purge takes what names it

Purging something from the trash now also deletes the reactions and recent
views that name it, and not only those on comments. Their row security asks
about the thing they name, so once it was gone nothing could delete them.

This deletes the ones earlier purges left: a reaction, a queued reaction
digest item or a recent view whose subject no longer exists. A trashed
subject still exists, so what names it stays. Not restored by the downgrade.

The kinds are stated here in full, so this revision reads the same whatever
the modules say later.

Revision ID: 20261001_0430
Revises: 20261001_0429
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20261001_0430"
down_revision = "20261001_0429"
branch_labels = None
depends_on = None

_REACTION_KINDS = {"comment": "comments", "post": "posts"}

_RECENT_KINDS = {
    "project": "projects",
    "document": "documents",
    "queue": "queues",
    "counter_group": "counter_groups",
    "calendar": "calendars",
    "dashboard": "dashboards",
    "post": "posts",
    "gallery": "galleries",
    "wiki": "wikis",
}

#: Each table that names its subject by ``(kind, id)``: its kind column, its
#: id column, and the table each kind's ids point at.
_NAMING = (
    ("reactions", "target_type", "target_id", _REACTION_KINDS),
    ("reaction_digest_items", "target_type", "target_id", _REACTION_KINDS),
    ("recent_views", "entity_type", "entity_id", _RECENT_KINDS),
)


def _orphaned(schema: str, kind_col: str, id_col: str, kinds: dict[str, str]) -> str:
    """The rows whose subject is not in its table. A kind not listed is kept."""
    arms = " ".join(
        f"WHEN '{kind}' THEN NOT EXISTS"
        f" (SELECT 1 FROM {schema}.{table} x WHERE x.id = t.{id_col})"
        for kind, table in kinds.items()
    )
    return f"CASE t.{kind_col} {arms} ELSE false END"


def _clear(bind, schema: str) -> None:
    """Delete ``schema``'s orphans. Every table here is FORCE RLS and a
    migration carries no request context, so the owner's policies are lifted
    before anything reads them and restored after; the triggers on the naming
    tables are about requests and are held while rows go."""
    read = {t for _, _, _, kinds in _NAMING for t in kinds.values()}
    tables = [f"{schema}.{t}" for t, *_ in _NAMING] + [
        f"{schema}.{t}" for t in sorted(read)
    ]
    for table in tables:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        for table, kind_col, id_col, kinds in _NAMING:
            where = _orphaned(schema, kind_col, id_col, kinds)
            count = sa.text(f"SELECT count(*) FROM {schema}.{table} t WHERE {where}")
            orphaned = bind.execute(count).scalar()
            if not orphaned:
                continue
            op.execute(f"ALTER TABLE {schema}.{table} DISABLE TRIGGER USER")
            op.execute(f"DELETE FROM {schema}.{table} t WHERE {where}")
            op.execute(f"ALTER TABLE {schema}.{table} ENABLE TRIGGER USER")
            left = bind.execute(count).scalar()
            assert left == 0, f"{schema}.{table}: {left} of {orphaned} remain"
    finally:
        for table in tables:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    for schema in guild_schema_names(bind):
        if schema.removeprefix("guild_").isdigit():
            _clear(bind, schema)


def downgrade() -> None:
    pass
