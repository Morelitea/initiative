"""The search index registry — which tables are searchable, and how.

One declaration per searchable table in :data:`SEARCH_SOURCES`, from which two
things are rendered: the trigger that keeps ``search_entries`` current, and the
default query scope. Adding a searchable table is one entry here.

Nothing declares *which* initiative a row belongs to. That is read from the same
``INITIATIVE_PATHS`` entry that renders the table's RLS policies, so a row cannot
be gated by one initiative and indexed under another — the argument
``event_capture`` already makes for reusing that registry, applied again.

Chunking is a length rule, not a per-table setting: an extractor yields text and
the trigger splits it if it is long. A tag's name is one chunk by the same code
path that gives a long document several.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import MetaData
from sqlmodel import SQLModel

from app.core.tools import Tool
from app.db.initiative_rls import initiative_locator

#: How a row reaches the trigger's dynamic lookups: as ``$1`` in an EXECUTE.
ROW = "($1)"

SEARCH_FUNCTION = "public.refresh_search_entry"

#: Target size of one chunk's body text, and the ceiling on chunks per entity.
#: The ceiling is a backstop for a pathological spreadsheet; ordinary content is
#: nowhere near it.
CHUNK_CHARS = 8000
MAX_CHUNKS = 2000


@dataclass(frozen=True)
class SearchSource:
    """How one table's rows become search entries."""

    #: Value stored in ``search_entries.entity_type``.
    entity_type: str
    #: Column holding the row's display title (weighted 'A').
    title: str
    #: Columns concatenated into the body (weighted 'B'), in order.
    body: tuple[str, ...] = ()
    #: The tool whose sharing governs this row, and the column naming the
    #: resource id to test. ``dac_id=None`` means the row's own ``id``.
    #: ``dac_tool=None`` means the row carries no sharing gate (a tag).
    dac_tool: Tool | None = None
    dac_id: str | None = None
    #: Whether this source is searched when the caller names no types. False
    #: puts the source behind an explicit opt-in and out of the default index.
    in_default_scope: bool = True

    @property
    def trigger_name(self) -> str:
        """Stem for this table's triggers; INSERT/DELETE and UPDATE are split
        (a WHEN clause naming OLD is invalid on INSERT)."""
        return f"search_{self.entity_type}"


#: table -> how its rows are indexed.
#:
#: ``comments`` is deliberately absent for now: it resolves its tool per row and
#: is the highest-volume source, so it arrives with the toggle and the partial
#: index that keep it off the default scope.
SEARCH_SOURCES: dict[str, SearchSource] = {
    "projects": SearchSource(
        "project", title="name", body=("description",), dac_tool=Tool.project
    ),
    "tasks": SearchSource(
        "task",
        title="title",
        body=("description",),
        dac_tool=Tool.project,
        dac_id="project_id",
    ),
    "documents": SearchSource(
        "document",
        title="name",
        # ``content`` extraction arrives with the per-document_type extractors;
        # the uploaded filename is plain text and useful on its own.
        body=("original_filename",),
        dac_tool=Tool.document,
    ),
    "queues": SearchSource(
        "queue", title="name", body=("description",), dac_tool=Tool.queue
    ),
    "queue_items": SearchSource(
        "queue_item",
        title="label",
        body=("notes",),
        dac_tool=Tool.queue,
        dac_id="queue_id",
    ),
    "counter_groups": SearchSource(
        "counter_group",
        title="name",
        body=("description",),
        dac_tool=Tool.counter_group,
    ),
    "counters": SearchSource(
        "counter",
        title="name",
        dac_tool=Tool.counter_group,
        dac_id="counter_group_id",
    ),
    "calendars": SearchSource(
        "calendar", title="name", body=("description",), dac_tool=Tool.calendar
    ),
    "calendar_events": SearchSource(
        "calendar_event",
        title="title",
        body=("description", "location"),
        dac_tool=Tool.calendar,
        dac_id="calendar_id",
    ),
    "dashboards": SearchSource(
        "dashboard", title="name", body=("description",), dac_tool=Tool.dashboard
    ),
    # Guild-level vocabulary: no initiative, no sharing gate. Reaching the query
    # at all means being in the guild, which is the whole gate for a tag.
    "tags": SearchSource("tag", title="name"),
}

#: Tables that are deliberately NOT searchable, and why. Every guild content
#: table is in exactly one of this or SEARCH_SOURCES; ``search_index_test``
#: fails until a new one is placed, so a table ships searchable by default or
#: says why not.
NOT_SEARCHABLE: dict[str, str] = {
    "search_entries": "the index itself",
    "event_outbox": "change log, not content",
    "resource_grants": "sharing rows carry no text",
    "property_definitions": "field config, reached from the tool it configures",
    "webhook_subscriptions": "integration config",
    "recent_views": "one member's own viewing state",
    "project_filter_presets": "one member's saved filters",
    "task_statuses": "column names, reached from the project",
    "document_file_versions": "history of a document already indexed",
    "document_links": "derived wikilink graph",
    "subtasks": "checklist lines, reached from the task",
    "comments": "arrives with the per-guild toggle and partial index",
    "initiatives": "structural; discovery is the join surface, not search",
    "event_reminder_dispatches": "scheduler bookkeeping",
    "task_assignment_digest_items": "scheduler bookkeeping",
}


#: A junction row is not a search result: it has no id to address and no text of
#: its own. Their composite primary key says so, which is the same derivation
#: ``event_capture`` uses to report them against their parent — so they are
#: excluded by construction rather than by a list that would need maintaining.
def addressable_tables(metadata: MetaData) -> set[str]:
    """Guild content tables a search hit could name — those with an ``id``."""
    return {
        name
        for name, table in metadata.tables.items()
        if [c.name for c in table.primary_key.columns] == ["id"]
    }


def entity_types(*, default_scope_only: bool = False) -> tuple[str, ...]:
    """Indexed entity types, sorted. The default-scope subset is what a query
    naming no types searches."""
    return tuple(
        sorted(
            s.entity_type
            for s in SEARCH_SOURCES.values()
            if s.in_default_scope or not default_scope_only
        )
    )


def _text_expr(columns: tuple[str, ...], row: str = ROW) -> str:
    """Row expression concatenating columns into one text value."""
    if not columns:
        return ""
    parts = [f"coalesce({row}.{c}, '')" for c in columns]
    return " || ' ' || ".join(parts) if len(parts) > 1 else parts[0]


def _quoted(expr: str) -> str:
    """A SQL expression as a trigger-argument string literal."""
    return "'" + expr.replace("'", "''") + "'"


def _when_clause(table: str, source: SearchSource) -> str:
    """Columns whose change makes a row's index entry stale.

    The trigger does not fire unless one of these actually changed, so the
    status moves, assignee changes and reordering that dominate writes to
    ``tasks`` cost nothing at all.
    """
    watched = [source.title, *source.body]
    if source.dac_id:
        watched.append(source.dac_id)
    watched.append("deleted_at")
    columns = SQLModel.metadata.tables[table].columns
    present = [c for c in dict.fromkeys(watched) if c in columns]
    return " OR ".join(f"OLD.{c} IS DISTINCT FROM NEW.{c}" for c in present)


WRITE_FUNCTION = "public.search_entry_write"

#: Splits one entity's text into chunks and replaces its rows. Shared by the
#: refresh trigger and the reindex sweep so both produce identical entries.
WRITE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION {write_fn}(
    p_schema      text,
    p_entity_type text,
    p_entity_id   integer,
    p_initiative  integer,
    p_dac_tool    text,
    p_dac_id      integer,
    p_title       text,
    p_body        text
) RETURNS void
    LANGUAGE plpgsql AS $write$
DECLARE
    v_title text := coalesce(p_title, '');
    v_body  text := coalesce(p_body, '');
    v_chunk text;
    v_ix    smallint := 0;
    v_pos   integer := 1;
    v_len   integer;
    v_cut   integer;
    v_space integer;
    c_chunk constant integer := {chunk};
    c_max   constant integer := {maxchunks};
BEGIN
    EXECUTE format(
        'DELETE FROM %I.search_entries WHERE entity_type = $1 AND entity_id = $2',
        p_schema
    ) USING p_entity_type, p_entity_id;

    v_len := length(v_body);

    -- One row per chunk, and always at least one so a titled entity with no
    -- body is still findable. Short text takes this loop exactly once.
    LOOP
        IF v_pos > v_len THEN
            v_chunk := '';
            v_cut := 0;
        ELSE
            v_cut := least(c_chunk, v_len - v_pos + 1);
            v_chunk := substr(v_body, v_pos, v_cut);
            -- Prefer a whitespace boundary when more text follows, so a chunk
            -- does not end mid-word.
            IF v_pos + v_cut - 1 < v_len THEN
                v_space := strpos(reverse(v_chunk), ' ');
                IF v_space > 0 AND (length(v_chunk) - v_space) > c_chunk / 2 THEN
                    v_cut := length(v_chunk) - v_space;
                    v_chunk := substr(v_chunk, 1, v_cut);
                    v_cut := v_cut + 1;
                END IF;
            END IF;
        END IF;

        EXECUTE format(
            'INSERT INTO %I.search_entries ('
            '  entity_type, entity_id, chunk_ix, initiative_id,'
            '  dac_tool, dac_id, title, body, updated_at, tsv'
            ') VALUES ($1, $2, $3, $4, nullif($5, ''''), $6, $7, nullif($8, ''''), now(),'
            '  setweight(to_tsvector(''simple'', $7), ''A'') ||'
            '  setweight(to_tsvector(''simple'', $8), ''B''))',
            p_schema
        ) USING p_entity_type, p_entity_id, v_ix, p_initiative,
                p_dac_tool, p_dac_id, v_title, v_chunk;

        v_ix := v_ix + 1;
        v_pos := v_pos + v_cut;
        EXIT WHEN v_pos > v_len OR v_ix >= c_max;
    END LOOP;
END
$write$;
""".format(write_fn=WRITE_FUNCTION, chunk=CHUNK_CHARS, maxchunks=MAX_CHUNKS)


SEARCH_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger
    LANGUAGE plpgsql AS $search$
DECLARE
    v_row        record;
    v_entity     integer;
    v_initiative integer;
    v_dac_id     integer;
    v_title      text;
    v_body       text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_row := OLD;
    ELSE
        v_row := NEW;
    END IF;

    EXECUTE 'SELECT ' || TG_ARGV[2] INTO v_entity USING v_row;
    IF v_entity IS NULL THEN
        RETURN NULL;
    END IF;

    -- A delete, or a soft delete, leaves the entity with no rows: trash is
    -- browsed through the trash surface, not found by searching.
    IF TG_OP = 'DELETE'
       OR (to_jsonb(v_row) ? 'deleted_at'
           AND to_jsonb(v_row) ->> 'deleted_at' IS NOT NULL) THEN
        EXECUTE format(
            'DELETE FROM %I.search_entries WHERE entity_type = $1 AND entity_id = $2',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[1], v_entity;
        RETURN NULL;
    END IF;

    EXECUTE 'SELECT ' || TG_ARGV[0] INTO v_initiative USING v_row;
    EXECUTE 'SELECT ' || TG_ARGV[3] INTO v_title USING v_row;
    IF TG_ARGV[4] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[4] INTO v_body USING v_row;
    END IF;
    IF TG_ARGV[6] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[6] INTO v_dac_id USING v_row;
    END IF;

    PERFORM {write_fn}(
        TG_TABLE_SCHEMA, TG_ARGV[1], v_entity, v_initiative,
        nullif(TG_ARGV[5], ''), v_dac_id, v_title, v_body
    );
    RETURN NULL;
END
$search$;
""".format(fn=SEARCH_FUNCTION, write_fn=WRITE_FUNCTION)


def _call_args(table: str, source: SearchSource) -> list[str]:
    """The seven trigger arguments, shared by both triggers on a table."""
    locator = initiative_locator(table)
    dac_id = f"{ROW}.{source.dac_id}" if source.dac_id else f"{ROW}.id"
    return [
        f"    {_quoted(locator(ROW))},",
        f"    '{source.entity_type}',",
        f"    {_quoted(f'{ROW}.id')},",
        f"    {_quoted(f'{ROW}.{source.title}')},",
        f"    {_quoted(_text_expr(source.body))},",
        f"    '{source.dac_tool.value if source.dac_tool else ''}',",
        f"    {_quoted(dac_id if source.dac_tool else '')}",
    ]


def _trigger_block(table: str, source: SearchSource) -> str:
    """DDL installing the two refresh triggers on one source table.

    Split by operation because the UPDATE one carries a ``WHEN`` clause naming
    ``OLD``, which is invalid on INSERT. That clause is the point: an update
    touching none of the indexed columns never enters the function.
    """
    args = _call_args(table, source)
    ins, upd = f"{source.trigger_name}_ins", f"{source.trigger_name}_upd"
    lines = [
        f"DROP TRIGGER IF EXISTS {source.trigger_name} ON {table};",
        f"DROP TRIGGER IF EXISTS {ins} ON {table};",
        f"CREATE TRIGGER {ins}",
        f"  AFTER INSERT OR DELETE ON {table}",
        f"  FOR EACH ROW EXECUTE FUNCTION {SEARCH_FUNCTION}(",
        *args,
        "  );",
        "",
        f"DROP TRIGGER IF EXISTS {upd} ON {table};",
        f"CREATE TRIGGER {upd}",
        f"  AFTER UPDATE ON {table}",
        f"  FOR EACH ROW WHEN ({_when_clause(table, source)})",
        f"  EXECUTE FUNCTION {SEARCH_FUNCTION}(",
        *args,
        "  );",
    ]
    return "\n".join(lines)


_HEADER = """\
-- ============================================================================
-- SEARCH INDEX — GENERATED, DO NOT EDIT BY HAND
-- RENDERED AT RUNTIME from app/db/search_index.py.
--
-- One trigger per searchable content table, all calling
-- public.refresh_search_entry(). Per-table knowledge is passed as trigger
-- arguments derived from SEARCH_SOURCES (title, body, sharing) and
-- INITIATIVE_PATHS (which initiative a row belongs to), so a new searchable
-- table is indexed without a second declaration.
-- ============================================================================"""


SEARCH_INDEX = "ix_search_entries_tsv"


def _index_block(opclass: str | None) -> str:
    """DDL asserting the index is built on ``opclass``, rebuilding only if not.

    Rendered here rather than left to the reflected structure DDL, which emits
    ``CREATE INDEX IF NOT EXISTS`` and so would keep whichever index a schema
    already has. Because the rendered text names the operator class, installing
    or removing it changes the provisioning stamp, and the next boot re-asserts
    the index for every guild.
    """
    marker = opclass.split(".")[-1] if opclass else ""
    using = f"gin (tsv {opclass})" if opclass else "gin (tsv)"
    # With a class: rebuild unless already on it. Without: rebuild if it is on
    # one, so removing the objects leaves a usable index behind.
    condition = (
        f"current_def IS NULL OR position('{marker}' in current_def) = 0"
        if marker
        else "current_def IS NULL OR position('_search_ops' in current_def) > 0"
    )
    return (
        "DO $$\n"
        "DECLARE current_def text;\n"
        "BEGIN\n"
        "    SELECT indexdef INTO current_def FROM pg_indexes\n"
        f"     WHERE schemaname = current_schema() AND indexname = '{SEARCH_INDEX}';\n"
        f"    IF {condition} THEN\n"
        f"        EXECUTE 'DROP INDEX IF EXISTS {SEARCH_INDEX}';\n"
        f"        EXECUTE 'CREATE INDEX {SEARCH_INDEX} ON search_entries "
        f"USING {using}';\n"
        "    END IF;\n"
        "END\n"
        "$$;"
    )


def render_guild_search_ddl(opclass: str | None = None) -> str:
    """Per-table trigger DDL plus the index, applied inside each guild schema.

    ``opclass`` is the operator class the index is built on, or ``None`` for the
    stock one.
    """
    blocks = [
        _trigger_block(table, source)
        for table, source in sorted(SEARCH_SOURCES.items())
    ]
    blocks.append(_index_block(opclass))
    return _HEADER + "\n\n" + "\n\n".join(blocks) + "\n"


def search_generation() -> str:
    """Digest of WHAT is indexed and HOW, for deciding when to reindex.

    Covers the per-source declarations and the chunking rules, so adding a
    source or changing an extraction re-sweeps. Deliberately excludes the index
    definition: swapping the operator class rebuilds the index, which does not
    change a single stored row.
    """
    digest = hashlib.sha256()
    for table, source in sorted(SEARCH_SOURCES.items()):
        digest.update(_trigger_block(table, source).encode())
    digest.update(WRITE_FUNCTION_SQL.encode())
    return f"search:{digest.hexdigest()[:16]}"


def reindex_statement(table: str, source: SearchSource) -> str:
    """One batch of a source table's rows, re-written through the same function
    the trigger uses.

    ``:schema`` names the guild schema, ``:cursor`` is the last id of the
    previous batch and ``:batch`` its size — so a large table is walked in
    bounded transactions rather than one.
    """
    row = "t"
    columns = SQLModel.metadata.tables[table].columns
    dac_tool = f"'{source.dac_tool.value}'" if source.dac_tool else "NULL"
    dac_id = (
        f"{row}.{source.dac_id or 'id'}::integer"
        if source.dac_tool
        else "NULL::integer"
    )
    body = _text_expr(source.body, row) or "''"
    live = " AND t.deleted_at IS NULL" if "deleted_at" in columns else ""
    return (
        f"SELECT {row}.id AS id, {WRITE_FUNCTION}("  # noqa: S608 — registry-rendered
        f":schema, '{source.entity_type}', {row}.id,"
        f" ({initiative_locator(table)(row)})::integer,"
        f" {dac_tool}, {dac_id}, {row}.{source.title}, {body})"
        f" FROM {table} {row}"
        f" WHERE {row}.id > :cursor{live}"
        f" ORDER BY {row}.id LIMIT :batch"
        # Locks each row for the duration of the write, so the values written
        # are the row's current ones: a concurrent write to the same row
        # finishes first and this sees its result, rather than replacing it
        # with what the batch read a moment earlier.
        " FOR UPDATE"
    )


def reindex_plan() -> list[tuple[str, str]]:
    """``(entity_type, statement)`` for every indexed source, in a stable order."""
    return [
        (source.entity_type, reindex_statement(table, source))
        for table, source in sorted(SEARCH_SOURCES.items())
    ]
