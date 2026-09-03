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
from collections.abc import Callable
from dataclasses import dataclass, replace

from sqlalchemy import MetaData
from sqlmodel import SQLModel

from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db.initiative_rls import COMMENT_PARENT_COLUMNS, initiative_locator

#: How a row reaches the trigger's dynamic lookups: as ``$1`` in an EXECUTE.
ROW = "($1)"

SEARCH_FUNCTION = "public.refresh_search_entry"

#: Target size of one chunk's body text, and the ceiling on chunks per entity.
#: The ceiling is a backstop for a pathological spreadsheet; ordinary content is
#: nowhere near it.
CHUNK_CHARS = 8000
MAX_CHUNKS = 2000

#: How much of a comment stands in for its title.
COMMENT_PREVIEW_CHARS = 140


@dataclass(frozen=True)
class SearchDependency:
    """A column on ANOTHER table that a source's stored gate is derived from.

    Almost every source names its parent in a column of its own, so its own
    trigger fires when that parent changes. A comment does not: it names a task,
    and the tool governing it is the task's PROJECT — so a task moving between
    projects moves the comment without touching the comment's row. Declared here,
    it gets a trigger on the table that moved, rewriting the entries that
    followed it.
    """

    #: The table whose column moves rows between gates.
    table: str
    #: The column on it that does the moving.
    column: str
    #: How the dependent source's rows tie back to it.
    local_column: str


@dataclass(frozen=True)
class SearchSource:
    """How one table's rows become search entries."""

    #: Value stored in ``search_entries.entity_type``.
    entity_type: SearchEntityType
    #: Column holding the row's display title (weighted 'A'). Also the column
    #: whose change makes the entry stale, even where ``title_sql`` builds the
    #: stored value from it.
    title: str
    #: Builds the title from a row alias, for a source whose title is not a
    #: column as it stands — a comment has no title, so it shows an opening.
    title_sql: Callable[[str], str] | None = None
    #: Columns feeding the body (weighted 'B'). Also the columns whose change
    #: makes the entry stale, so they drive the trigger's WHEN clause.
    body: tuple[str, ...] = ()
    #: Builds the body from a row alias, for a source whose text is not simply
    #: its columns concatenated. Takes precedence over ``body``; the columns are
    #: still declared above so the WHEN clause knows what to watch.
    body_sql: Callable[[str], str] | None = None
    #: The tool whose sharing governs this row, and the column naming the
    #: resource id to test. ``dac_id=None`` means the row's own ``id``.
    #: ``dac_tool=None`` means the row carries no sharing gate (a tag).
    dac_tool: Tool | None = None
    dac_id: str | None = None
    #: Builds ``(tool, id)`` from a row alias, for a source whose governing tool
    #: differs per row. Takes precedence over the pair above.
    dac_sql: Callable[[str], tuple[str, str]] | None = None
    #: Whether this source is searched when the caller names no types. False
    #: puts the source behind an explicit opt-in and out of the default index.
    in_default_scope: bool = True
    #: Columns on other tables that move these rows between gates.
    depends_on: tuple[SearchDependency, ...] = ()

    @property
    def trigger_name(self) -> str:
        """Stem for this table's triggers; INSERT/DELETE and UPDATE are split
        (a WHEN clause naming OLD is invalid on INSERT)."""
        return f"search_{self.entity_type.value}"


def _json_text(row: str, path: str, *, column: str = "content") -> str:
    """Text of every value a jsonpath selects, as one space-joined string.

    ``strict`` so a value reachable by more than one path is taken once —
    the lax form walks into arrays as well as their elements and would store
    the same text twice. ``silent`` so a shape that simply lacks the key
    yields nothing instead of raising.
    """
    return (
        "coalesce((SELECT string_agg(v #>> '{}', ' ') FROM jsonb_path_query("
        f"{row}.{column}, '{path}', '{{}}'::jsonb, true) v), '')"
    )


def _with_words(expr: str) -> str:
    """``expr``, plus the same value split on punctuation.

    A URL or a filename is tokenized as a whole — ``www.figma.com`` and
    ``vendor-contract-2026.pdf`` are each a single lexeme — so the words inside
    them are not findable on their own. Emitting a split copy alongside makes
    both work. Used only for these short, punctuation-dense fields; doing it to
    prose would double what is stored for nothing.
    """
    return f"{expr} || ' ' || regexp_replace({expr}, '[^[:alnum:]]+', ' ', 'g')"


def _document_text(row: str) -> str:
    """A document's searchable text, by what kind of document it is.

    ``content`` holds a different shape per type, so there is no single
    expression. ``native`` and ``whiteboard`` share one: a Lexical text node
    and an Excalidraw text or label element both keep their text in a field
    named ``text``, and the recursive path reaches nested cases — a mention, a
    wikilink, an image caption's own editor state.

    A ``file`` document contributes nothing here: its bytes live in ``uploads``,
    so its name, description and uploaded filename are all there is to index.
    """
    leaves = _json_text(row, "strict $.**.text")
    cells = (
        "coalesce((SELECT string_agg(v #>> '{}', ' ') FROM ("
        f"SELECT v FROM jsonb_path_query({row}.content, 'strict $.**.cells.*', "
        "'{}'::jsonb, true) v"
        " UNION ALL "
        f"SELECT v FROM jsonb_path_query({row}.content, 'strict $.sheets[*].name', "
        "'{}'::jsonb, true) v) s), '')"
    )
    url = _with_words(f"coalesce({row}.content ->> 'url', '')")
    return (
        f"(CASE {row}.document_type::text"
        f" WHEN 'native' THEN {leaves}"
        f" WHEN 'whiteboard' THEN {leaves}"
        f" WHEN 'spreadsheet' THEN {cells}"
        f" WHEN 'smart_link' THEN {url}"
        " ELSE '' END)"
        " || ' ' || " + _with_words(f"coalesce({row}.original_filename, '')")
    )


def _comment_preview(row: str) -> str:
    """The opening of a comment, as the line a result is shown by.

    A comment has no title. Storing the whole of one would put an essay where a
    name goes; the full text is still indexed as the body, so what matched is
    findable either way.
    """
    return f"left({row}.content, {COMMENT_PREVIEW_CHARS})"


def _comment_dac(row: str) -> tuple[str, str]:
    """Which tool's sharing governs a comment, and which of its entities.

    A comment hangs off exactly one parent, and the parents are declared once
    for the RLS policies — so the legs are derived from that same list rather
    than restated here. A comment on a task is the one leg whose id is not its
    own column: a task is shared as part of its project.
    """
    tools: list[str] = []
    ids: list[str] = []
    for column in COMMENT_PARENT_COLUMNS:
        if column == "task_id":
            tool, ident = (
                Tool.project,
                (f"(SELECT project_id FROM tasks WHERE id = {row}.task_id)"),
            )
        else:
            tool = Tool(column.removesuffix("_id"))
            ident = f"{row}.{column}"
        tools.append(f"WHEN {row}.{column} IS NOT NULL THEN '{tool.value}'")
        ids.append(f"WHEN {row}.{column} IS NOT NULL THEN {ident}")
    return f"(CASE {' '.join(tools)} END)", f"(CASE {' '.join(ids)} END)"


def _title_expr(source: "SearchSource", row: str = ROW) -> str:
    """Row expression yielding a source's stored title."""
    if source.title_sql is not None:
        return source.title_sql(row)
    return f"{row}.{source.title}"


#: Boolean columns that say a row is not part of the working set. Having the
#: column IS the declaration — a source states nothing, the same way ``deleted_at``
#: is read off the table rather than declared.
FLAG_COLUMNS: dict[str, str] = {"archived": "is_archived", "template": "is_template"}


def _flag_expr(table: str, flag: str, row: str) -> str | None:
    """Row expression for one flag, or ``None`` where the table cannot carry it."""
    column = FLAG_COLUMNS[flag]
    if column not in SQLModel.metadata.tables[table].columns:
        return None
    return f"{row}.{column}"


def _body_expr(source: "SearchSource", row: str = ROW) -> str:
    """Row expression yielding a source's body text."""
    if source.body_sql is not None:
        return source.body_sql(row)
    if not source.body:
        return ""
    parts = [f"coalesce({row}.{c}, '')" for c in source.body]
    return " || ' ' || ".join(parts) if len(parts) > 1 else parts[0]


#: How a tool indexes when it says nothing: its own name and description, gated
#: by its own sharing. Stated once and applied to every member of ``Tool``, so a
#: seventh tool is searchable the day its table exists.
def _tool_source(tool: Tool) -> SearchSource:
    return SearchSource(
        SearchEntityType(tool.value),
        title="name",
        body=("description",),
        dac_tool=tool,
    )


#: Where a tool's text is not simply its name and description. A tool absent
#: from here is not an omission — it is a tool that takes the shape above.
TOOL_OVERRIDES: dict[Tool, dict[str, object]] = {
    Tool.document: {
        "body": ("content", "document_type", "original_filename"),
        "body_sql": _document_text,
    },
}

#: table -> how its rows are indexed.
#:
#: The six tools are derived; what is written out is what a tool does not
#: describe — the entities that live INSIDE one, the guild's vocabulary, and
#: comments. Those differ from each other in ways no rule covers: which column
#: is the title, which parent's sharing governs them.
SEARCH_SOURCES: dict[str, SearchSource] = {
    **{
        tool.plural: replace(_tool_source(tool), **TOOL_OVERRIDES.get(tool, {}))
        for tool in Tool
    },
    "tasks": SearchSource(
        SearchEntityType.task,
        title="title",
        body=("description",),
        dac_tool=Tool.project,
        dac_id="project_id",
    ),
    "queue_items": SearchSource(
        SearchEntityType.queue_item,
        title="label",
        body=("notes",),
        dac_tool=Tool.queue,
        dac_id="queue_id",
    ),
    "counters": SearchSource(
        SearchEntityType.counter,
        title="name",
        dac_tool=Tool.counter_group,
        dac_id="counter_group_id",
    ),
    "calendar_events": SearchSource(
        SearchEntityType.calendar_event,
        title="title",
        body=("description", "location"),
        dac_tool=Tool.calendar,
        dac_id="calendar_id",
    ),
    # Guild-level vocabulary: no initiative, no sharing gate. Reaching the query
    # at all means being in the guild, which is the whole gate for a tag.
    "tags": SearchSource(SearchEntityType.tag, title="name"),
    # What people said on the content above. Out of the default scope: it is the
    # highest-volume table in a busy guild, and a caller that wants it says so —
    # which is what the results page's own tab does.
    "comments": SearchSource(
        SearchEntityType.comment,
        title="content",
        title_sql=_comment_preview,
        body=("content",),
        dac_sql=_comment_dac,
        in_default_scope=False,
        # A comment on a task is governed by the task's project, and a task can
        # move between projects. Nothing about the comment changes when it does,
        # so the entry is rewritten from the table that moved. Every other
        # parent names its own initiative and cannot move between them.
        depends_on=(SearchDependency("tasks", "project_id", "task_id"),),
    ),
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
    "initiatives": "structural; discovery is the join surface, not search",
    "event_reminder_dispatches": "scheduler bookkeeping",
    "task_assignment_digest_items": "scheduler bookkeeping",
    "reaction_digest_items": "scheduler bookkeeping",
    "reactions": "a gesture with no text of its own",
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


def entity_types(*, default_scope_only: bool = False) -> tuple[SearchEntityType, ...]:
    """Indexed entity types, sorted. The default-scope subset is what a query
    naming no types searches."""
    return tuple(
        sorted(
            (
                s.entity_type
                for s in SEARCH_SOURCES.values()
                if s.in_default_scope or not default_scope_only
            ),
            key=lambda t: t.value,
        )
    )


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
    watched.extend(FLAG_COLUMNS.values())
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
    p_body        text,
    p_archived    boolean,
    p_template    boolean
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
            '  dac_tool, dac_id, title, body, archived, template, updated_at, tsv'
            ') VALUES ($1, $2, $3, $4, nullif($5, ''''), $6, $7, nullif($8, ''''),'
            '  coalesce($9, false), coalesce($10, false), now(),'
            '  setweight(to_tsvector(''simple'', $7), ''A'') ||'
            '  setweight(to_tsvector(''simple'', $8), ''B''))',
            p_schema
        ) USING p_entity_type, p_entity_id, v_ix, p_initiative,
                p_dac_tool, p_dac_id, v_title, v_chunk,
                p_archived, p_template;

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
    v_dac_tool   text;
    v_archived   boolean := false;
    v_template   boolean := false;
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
    IF TG_ARGV[5] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[5] INTO v_dac_tool USING v_row;
        EXECUTE 'SELECT ' || TG_ARGV[6] INTO v_dac_id USING v_row;
    END IF;
    IF TG_ARGV[7] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[7] INTO v_archived USING v_row;
    END IF;
    IF TG_ARGV[8] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[8] INTO v_template USING v_row;
    END IF;

    PERFORM {write_fn}(
        TG_TABLE_SCHEMA, TG_ARGV[1], v_entity, v_initiative,
        v_dac_tool, v_dac_id, v_title, v_body,
        v_archived, v_template
    );
    RETURN NULL;
END
$search$;
""".format(fn=SEARCH_FUNCTION, write_fn=WRITE_FUNCTION)


def _dac_exprs(source: SearchSource) -> tuple[str, str]:
    """The ``(tool, id)`` expressions naming a row's sharing gate, or empty
    strings where the source has none."""
    if source.dac_sql is not None:
        return source.dac_sql(ROW)
    if source.dac_tool is None:
        return "", ""
    dac_id = f"{ROW}.{source.dac_id}" if source.dac_id else f"{ROW}.id"
    return f"'{source.dac_tool.value}'::text", dac_id


DEPENDENT_FUNCTION = "public.refresh_search_dependents"

#: Rewrites the entries of rows that moved because a column on ANOTHER table
#: changed. The statement is rendered per dependency and passed whole, so a row
#: rewritten here goes through the same expressions as one rewritten by its own
#: trigger or by the sweep.
DEPENDENT_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger
    LANGUAGE plpgsql AS $dep$
BEGIN
    EXECUTE TG_ARGV[0] USING TG_TABLE_SCHEMA, NEW.id;
    RETURN NULL;
END
$dep$;
""".format(fn=DEPENDENT_FUNCTION)


def _live_clause(table: str, row: str) -> str:
    """Restricts to rows that have an entry at all — trash is browsed through
    the trash surface, not found by searching."""
    columns = SQLModel.metadata.tables[table].columns
    return f" AND {row}.deleted_at IS NULL" if "deleted_at" in columns else ""


def _write_call(table: str, source: SearchSource, row: str, schema: str) -> str:
    """The ``search_entry_write`` call for one row of a source, as SQL.

    The sweep and the dependency triggers both go through this, so a row
    rewritten by either is written identically.
    """
    dac_tool_expr, dac_id_expr = _dac_exprs(source)
    dac_tool = dac_tool_expr.replace(ROW, row) if dac_tool_expr else "NULL::text"
    dac_id = (
        f"({dac_id_expr.replace(ROW, row)})::integer"
        if dac_id_expr
        else "NULL::integer"
    )
    body = _body_expr(source, row) or "''"
    archived = _flag_expr(table, "archived", row) or "false"
    template = _flag_expr(table, "template", row) or "false"
    return (
        f"{WRITE_FUNCTION}({schema}, '{source.entity_type.value}', {row}.id,"
        f" ({initiative_locator(table)(row)})::integer,"
        f" {dac_tool}, {dac_id}, {_title_expr(source, row)}, {body},"
        f" {archived}, {template})"
    )


def _dependency_block(
    table: str, source: SearchSource, dependency: SearchDependency
) -> str:
    """DDL for the trigger that rewrites entries when a row moves under them.

    ``$1`` is the guild schema and ``$2`` the id of the row that moved. The
    dependent table is named unqualified, as every other rendered expression is:
    the trigger runs with its own schema first on the search path.
    """
    row = "t"
    statement = (
        f"SELECT {_write_call(table, source, row, '$1')}"  # noqa: S608 — rendered
        f" FROM {table} {row}"
        f" WHERE {row}.{dependency.local_column} = $2{_live_clause(table, row)}"
    )
    name = f"{source.trigger_name}_from_{dependency.table}"
    return "\n".join(
        [
            f"DROP TRIGGER IF EXISTS {name} ON {dependency.table};",
            f"CREATE TRIGGER {name}",
            f"  AFTER UPDATE ON {dependency.table}",
            f"  FOR EACH ROW WHEN (OLD.{dependency.column} "
            f"IS DISTINCT FROM NEW.{dependency.column})",
            f"  EXECUTE FUNCTION {DEPENDENT_FUNCTION}({_quoted(statement)});",
        ]
    )


def _call_args(table: str, source: SearchSource) -> list[str]:
    """The nine trigger arguments, shared by both triggers on a table.

    An argument is the empty string where the source has nothing to say — no
    body, no sharing gate, no flag column — and the function skips it.
    """
    locator = initiative_locator(table)
    dac_tool, dac_id = _dac_exprs(source)
    return [
        f"    {_quoted(locator(ROW))},",
        f"    '{source.entity_type.value}',",
        f"    {_quoted(f'{ROW}.id')},",
        f"    {_quoted(_title_expr(source))},",
        f"    {_quoted(_body_expr(source))},",
        f"    {_quoted(dac_tool)},",
        f"    {_quoted(dac_id)},",
        f"    {_quoted(_flag_expr(table, 'archived', ROW) or '')},",
        f"    {_quoted(_flag_expr(table, 'template', ROW) or '')}",
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
ENTITY_TYPE_CHECK = "ck_search_entries_entity_type"


def _entity_type_check_block() -> str:
    """DDL asserting the entity-type CHECK names exactly the indexed set.

    Rendered here rather than migrated so the list has one home. A migration
    would freeze a snapshot of it, and the next source added would be rejected
    at write time by a constraint nobody remembered to widen; because this text
    names the types, adding one moves the provisioning stamp and the next boot
    re-asserts the constraint for every guild.
    """
    values = ", ".join(f"'{t.value}'" for t in entity_types())
    return (
        f"ALTER TABLE search_entries DROP CONSTRAINT IF EXISTS {ENTITY_TYPE_CHECK};\n"
        f"ALTER TABLE search_entries ADD CONSTRAINT {ENTITY_TYPE_CHECK}\n"
        f"    CHECK (entity_type IN ({values}));"
    )


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
    blocks.extend(
        _dependency_block(table, source, dependency)
        for table, source in sorted(SEARCH_SOURCES.items())
        for dependency in source.depends_on
    )
    blocks.append(_entity_type_check_block())
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
    return (
        f"SELECT {row}.id AS id,"  # noqa: S608 — registry-rendered
        f" {_write_call(table, source, row, ':schema')}"
        f" FROM {table} {row}"
        f" WHERE {row}.id > :cursor{_live_clause(table, row)}"
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
        (source.entity_type.value, reindex_statement(table, source))
        for table, source in sorted(SEARCH_SOURCES.items())
    ]
