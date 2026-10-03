"""a mention keeps no name

A mention of somebody with an account is stored by id alone, and the app takes
the name out on every write. This takes it out of what was written before:
``@[Ada](42)`` becomes ``@[](42)`` in text, and a Lexical mention node keeps
its ``mentionUserId`` with ``mentionName`` and ``text`` empty. A mention of
somebody with no account keeps its name, which is all it has.

The columns are stated here rather than read from any registry, so this
revision reads the same whatever the modules say later. Archived, template and
trashed rows are rewritten too. A document or wiki page that mentions somebody
loses its ``yjs_state``, which an editor from before can have written a name
into, so collaboration starts again from the content. The
tables' row security and request triggers (the freeze, change capture,
search) are held while rows change, and a guild with rows changed has its
search marker cleared, so the next start reindexes it.

The downgrade leaves content as it is: the names are kept nowhere.

Revision ID: 20261002_0444
Revises: 20261002_0443
Create Date: 2026-10-02
"""

import json
import re
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

from app.db.guild_migrations import guild_schema_names

revision = "20261002_0444"
down_revision = "20261002_0443"
branch_labels = None
depends_on = None

#: A markdown mention that still carries a name, as Python and Postgres read it.
_NAMED = r"@\[[^\]]+\]\(([0-9]+)\)"
#: An editor-state mention node naming an account, in the column's text.
_NAMED_NODE = r'"mentionUserId":\s*[0-9]'

#: Markdown columns that can hold a mention.
TEXT_COLUMNS: dict[str, tuple[str, ...]] = {
    "calendar_events": ("description", "location"),
    "calendars": ("description",),
    "comments": ("content",),
    "counter_groups": ("description",),
    "dashboards": ("description",),
    "galleries": ("description",),
    "gallery_images": ("caption",),
    "initiatives": ("description",),
    "projects": ("description",),
    "queue_items": ("notes",),
    "queues": ("description",),
    "tasks": ("description",),
    "wikis": ("description",),
}
#: ``jsonb`` columns that can hold a mention: an editor state, or markdown
#: inside one (a checklist line, a repeat's description).
JSON_COLUMNS: dict[str, tuple[str, ...]] = {
    "documents": ("content",),
    "posts": ("body",),
    "tasks": ("checklist", "recurrence_carry"),
    "wiki_pages": ("content",),
}
#: Tables whose rows keep a collaboration state beside their ``content``.
_COLLABORATIVE = ("documents", "wiki_pages")


def _nameless(value: Any) -> tuple[Any, bool]:
    """``value`` with no mention by id carrying a name, and whether anything
    changed."""
    pattern = re.compile(_NAMED)
    changed = False

    def walk(node: Any) -> Any:
        nonlocal changed
        if isinstance(node, str):
            stripped = pattern.sub(r"@[](\1)", node)
            changed = changed or stripped != node
            return stripped
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        node = {key: walk(child) for key, child in node.items()}
        user_id = node.get("mentionUserId")
        if (
            isinstance(user_id, int)
            and not isinstance(user_id, bool)
            and (node.get("mentionName") or node.get("text"))
        ):
            node |= {"mentionName": "", "text": ""}
            changed = True
        return node

    return walk(value), changed


def strip_schema(bind: Connection, schema: str) -> None:
    """Take the names out of one guild schema's mentions, with the tables'
    row security and request triggers held while rows change."""
    tables = sorted({*TEXT_COLUMNS, *JSON_COLUMNS})
    for table in tables:
        bind.execute(
            sa.text(f'ALTER TABLE "{schema}".{table} NO FORCE ROW LEVEL SECURITY')
        )
        bind.execute(sa.text(f'ALTER TABLE "{schema}".{table} DISABLE TRIGGER USER'))
    try:
        changed = _strip(bind, schema)
    finally:
        for table in tables:
            bind.execute(sa.text(f'ALTER TABLE "{schema}".{table} ENABLE TRIGGER USER'))
            bind.execute(
                sa.text(f'ALTER TABLE "{schema}".{table} FORCE ROW LEVEL SECURITY')
            )
    if changed:
        bind.execute(sa.text(f'COMMENT ON TABLE "{schema}".search_entries IS NULL'))


def _strip(bind: Connection, schema: str) -> int:
    """The names taken out of one schema's mentions; the rows changed."""
    changed = 0
    for table, columns in TEXT_COLUMNS.items():
        for column in columns:
            changed += bind.execute(
                sa.text(
                    f'UPDATE "{schema}".{table}'  # noqa: S608 — stated names
                    f" SET {column} = regexp_replace({column}, :named, :id, 'g')"
                    f" WHERE {column} ~ :named"
                ),
                {"named": _NAMED, "id": r"@[](\1)"},
            ).rowcount
    for table, columns in JSON_COLUMNS.items():
        for column in columns:
            rows = bind.execute(
                sa.text(
                    f'SELECT id, {column} AS value FROM "{schema}".{table}'  # noqa: S608
                    f" WHERE {column}::text ~ :named OR {column}::text ~ :node"
                ),
                {"named": _NAMED, "node": _NAMED_NODE},
            ).all()
            for row in rows:
                value, did = _nameless(row.value)
                if not did:
                    continue
                bind.execute(
                    sa.text(
                        f'UPDATE "{schema}".{table}'  # noqa: S608
                        f" SET {column} = CAST(:value AS jsonb) WHERE id = :id"
                    ),
                    {"value": json.dumps(value), "id": row.id},
                )
                changed += 1
    for table in _COLLABORATIVE:
        bind.execute(
            sa.text(
                f'UPDATE "{schema}".{table} SET yjs_state = NULL'  # noqa: S608
                " WHERE yjs_state IS NOT NULL AND content::text ~ :node"
            ),
            {"node": _NAMED_NODE},
        )
    return changed


def upgrade() -> None:
    bind = op.get_bind()
    for schema in guild_schema_names(bind):
        if schema.removeprefix("guild_").isdigit():
            strip_schema(bind, schema)


def downgrade() -> None:
    # The names are kept nowhere to put back.
    pass
