"""Change capture — one trigger function, every evented content table.

The capture rule lives in ONE place, ``public.capture_change()``. Per-table
knowledge reaches it as trigger arguments rendered from the registry that already
describes these tables, so installing capture on a new table needs no new
declaration:

* **which initiative a row belongs to** — the ``INITIATIVE_PATHS`` entry that
  renders the table's RLS policies, so an event is scoped exactly like the row it
  describes;
* **which resource the event names** — the table's own primary key, or the parent
  it reports against (below).

What lands in ``event_outbox`` is identifiers, an action, and the **names** of
the columns that changed. Never a value: a consumer reads current state back
through the REST API, where the six gates apply to the read.

Sub-resources report their parent
---------------------------------
Over half these tables are junctions with a composite primary key
(``task_tags``, ``task_assignees``, ``document_property_values``, …) and no id
of their own. Their first primary-key column is always the FK to the resource
that owns them, so a row appearing in ``task_tags`` is reported as
``tasks.updated`` with ``changed = ['tags']``.

That is also the semantics a subscriber wants: "this task was tagged", not "a
row appeared in a junction table". The owner and the label are both derived —
the owner from the FK, the label by stripping the owner's singular stem from the
junction's name — so a new junction is covered by construction.

The same shape covers sub-resources that DO have an id of their own but are
still a facet of something else (a project's statuses, a document's versions, an
initiative's roles, a resource's sharing). Derivation cannot see that, so those
say it once in ``EVENT_SOURCES`` as a ``ReportsAs``. Either way the resource an
event names is one that already has a detail route, which is what keeps every
id in the outbox resolvable without owing new API surface per table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Column
from sqlmodel import SQLModel

from app.db.initiative_rls import (
    EVENTED_TABLES,
    event_source,
    initiative_locator,
)

#: How a row reaches the trigger's dynamic lookups: as ``$1`` in an EXECUTE, so
#: every registry expression is rendered against this rather than NEW/OLD.
ROW = "($1)"

#: The function name every per-table trigger calls. Created once in ``public``
#: (not per guild schema): the body names content tables unqualified, so it
#: resolves them through the caller's ``search_path`` — the routed guild schema —
#: exactly as ``public.initiative_access`` does.
CAPTURE_FUNCTION = "public.capture_change"

#: Columns whose changes are not worth reporting. ``updated_at`` moves on every
#: write, and search vectors / denormalized counters churn on their own, so
#: leaving them in would make every column filter match constantly.
HOUSEKEEPING_COLUMNS: frozenset[str] = frozenset(
    {"updated_at", "created_at", "search_vector"}
)

#: Same idea, by suffix, for generated text-search columns.
HOUSEKEEPING_SUFFIXES: tuple[str, ...] = ("_vector", "_tsv")


@dataclass(frozen=True)
class CaptureSpec:
    """How one table's changes are reported."""

    #: The table the trigger is installed on.
    table: str
    #: The resource types an event from this table can name — the table itself,
    #: or the parent it reports against. More than one only for a polymorphic
    #: facet (a grant names whichever tool it is on).
    resource_types: frozenset[str]
    #: Row expression yielding that resource's id.
    resource_id_expr: str
    #: When the table reports against a parent, the label used in ``changed``
    #: (e.g. ``tags``). ``None`` when the table is its own resource and real
    #: column names apply.
    facet: str | None
    #: Row expression yielding the resource type, for the polymorphic case.
    #: ``None`` when ``resource_types`` holds the single constant answer.
    resource_type_expr: str | None = None

    @property
    def trigger_name(self) -> str:
        return f"capture_{self.table}"

    @property
    def static_resource_type(self) -> str:
        """The one type this names, for the ordinary non-polymorphic case."""
        (resource_type,) = self.resource_types
        return resource_type


def _singular(table: str) -> str:
    """Junction owners are all regular plurals in this schema."""
    return table[:-1] if table.endswith("s") else table


def _owner_of(column: Column[Any]) -> str | None:
    """The table a FK column points at, or None if it is not a FK."""
    for fk in column.foreign_keys:
        return fk.column.table.name
    return None


def build_specs() -> list[CaptureSpec]:
    """One spec per evented table.

    Three sources, tried in order: a declared ``ReportsAs`` (the explicit facet),
    a composite primary key (the derived facet), or the table's own primary key.

    Raises when a table can be reported none of those ways — capture would
    otherwise install a trigger that emits rows naming no resource, and a
    silently unaddressable event is worse than a failed boot.
    """
    specs: list[CaptureSpec] = []
    for table_name in sorted(EVENTED_TABLES):
        table = SQLModel.metadata.tables.get(table_name)
        if table is None:
            raise RuntimeError(
                f"{table_name} is in EVENTED_TABLES but has no mapped model"
            )

        declared = event_source(table_name).reports_as
        if declared is not None:
            specs.append(
                CaptureSpec(
                    table=table_name,
                    resource_types=declared.resource_types,
                    resource_id_expr=declared.id_expr(ROW),
                    facet=declared.facet,
                    resource_type_expr=(
                        declared.type_expr(ROW)
                        if declared.type_expr is not None
                        else None
                    ),
                )
            )
            continue

        pk = list(table.primary_key.columns)
        if len(pk) == 1:
            specs.append(
                CaptureSpec(
                    table=table_name,
                    resource_types=frozenset({table_name}),
                    resource_id_expr=f'{ROW}."{pk[0].name}"',
                    facet=None,
                )
            )
            continue

        owner_column = pk[0]
        owner = _owner_of(owner_column)
        if owner is None:
            raise RuntimeError(
                f"{table_name} has a composite primary key whose first column "
                f"({owner_column.name}) is not a foreign key, so its events "
                "cannot name an owning resource"
            )
        specs.append(
            CaptureSpec(
                table=table_name,
                resource_types=frozenset({owner}),
                resource_id_expr=f'{ROW}."{owner_column.name}"',
                facet=table_name.removeprefix(f"{_singular(owner)}_"),
            )
        )
    return specs


# ---------------------------------------------------------------------------
# The capture function
# ---------------------------------------------------------------------------

#: Rendered once into ``public``. Per-table knowledge arrives as TG_ARGV, where
#: every "expression" is SQL text evaluated with the changed row as ``$1``:
#:   0 — expression resolving the row's initiative id
#:   1 — resource type the event names
#:   2 — expression resolving that resource's id
#:   3 — facet label, or '' when the table is its own resource
#:   4 — array literal of column names excluded from ``changed``
#:   5 — 'guild' when this table has no initiative and a NULL is expected
#:   6 — expression resolving the resource TYPE, or '' when arg 1 is the answer
CAPTURE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {CAPTURE_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $capture$
DECLARE
    v_row        record;
    v_initiative integer;
    v_action     text;
    v_changed    text[] := '{{}}';
    v_resource   integer;
    v_type       text := TG_ARGV[1];
    v_actor      integer;
    v_new        jsonb;
    v_old        jsonb;
    v_facet      text := TG_ARGV[3];
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_row := OLD;
    ELSE
        v_row := NEW;
    END IF;

    -- Which initiative this row belongs to, per its registry entry. A NULL is
    -- expected for a guild-wide table and means exactly that; anywhere else it
    -- means the initiative no longer resolves — an orphaned child during a
    -- parent cascade, whose parent emits its own delete — so the row is skipped
    -- rather than broadcast without a scope.
    EXECUTE 'SELECT ' || TG_ARGV[0] INTO v_initiative USING v_row;
    IF v_initiative IS NULL AND TG_ARGV[5] <> 'guild' THEN
        RETURN NULL;
    END IF;

    EXECUTE 'SELECT ' || TG_ARGV[2] INTO v_resource USING v_row;
    IF v_resource IS NULL THEN
        RETURN NULL;
    END IF;

    -- A polymorphic facet names its parent's type per row (a grant reports
    -- against whichever tool it shares). An unrecognized value resolves to NULL
    -- and the row is skipped, so what a subscription may name and what can be
    -- emitted stay the same set.
    IF TG_ARGV[6] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[6] INTO v_type USING v_row;
        IF v_type IS NULL THEN
            RETURN NULL;
        END IF;
    END IF;

    IF TG_OP = 'INSERT' THEN
        v_action := 'created';
    ELSIF TG_OP = 'DELETE' THEN
        -- On a table with the trash lifecycle, deleting is soft: the row moves
        -- to the trash, which is the event a subscriber acts on, and this hard
        -- delete is retention clearing it out afterwards. Never surface that —
        -- it is a repeat of an announced delete, and by now nothing can resolve
        -- the id anyway, not even a read-back asking for trashed rows.
        --
        -- Carrying no deleted_at means the table has no other kind of delete,
        -- so that one IS the event: a junction row going away is how a task
        -- loses a tag.
        --
        -- Tested for through jsonb rather than as OLD.deleted_at, because most
        -- evented tables have no such column and naming one that is absent
        -- raises at runtime.
        IF to_jsonb(OLD) ? 'deleted_at' THEN
            RETURN NULL;
        END IF;
        v_action := 'deleted';
    ELSE
        v_new := to_jsonb(NEW);
        v_old := to_jsonb(OLD);

        -- Soft delete and restore are reported as what they are, so a consumer
        -- never has to know the deleted_at convention to see a row come or go.
        IF v_new ? 'deleted_at'
           AND v_old ->> 'deleted_at' IS NULL
           AND v_new ->> 'deleted_at' IS NOT NULL THEN
            v_action := 'deleted';
        ELSIF v_new ? 'deleted_at'
           AND v_old ->> 'deleted_at' IS NOT NULL
           AND v_new ->> 'deleted_at' IS NULL THEN
            v_action := 'created';
        ELSE
            v_action := 'updated';
            SELECT coalesce(array_agg(key ORDER BY key), '{{}}')
              INTO v_changed
              FROM jsonb_each(v_new) AS e(key, value)
             WHERE value IS DISTINCT FROM (v_old -> e.key)
               AND NOT (key = ANY (TG_ARGV[4]::text[]));

            -- Nothing a subscriber can act on changed.
            IF cardinality(v_changed) = 0 THEN
                RETURN NULL;
            END IF;
        END IF;
    END IF;

    -- A facet has no columns of its own worth naming; report the change as the
    -- owning resource being updated in one respect.
    IF v_facet <> '' THEN
        v_changed := ARRAY[v_facet];
        IF v_action <> 'updated' THEN
            v_action := 'updated';
        END IF;
    END IF;

    v_actor := NULLIF(current_setting('app.current_user_id', true), '')::integer;

    -- Write to the outbox of the schema the CHANGED ROW lives in, named from
    -- TG_TABLE_SCHEMA rather than resolved through the caller's search_path.
    -- The row's own schema is the authoritative answer to which guild this
    -- event belongs to, and it is what the trigger is attached to.
    EXECUTE format(
        'INSERT INTO %I.event_outbox ('
        '  txn_id, occurred_at, actor_user_id, initiative_id,'
        '  resource_type, resource_id, action, changed'
        ') VALUES (txid_current(), now(), $1, $2, $3, $4, $5, $6)',
        TG_TABLE_SCHEMA
    ) USING v_actor, v_initiative, v_type, v_resource, v_action, v_changed;

    RETURN NULL;
END
$capture$;
"""


def _housekeeping_literal(table_name: str) -> str:
    """SQL array literal of column names excluded from ``changed`` for a table."""
    table = SQLModel.metadata.tables[table_name]
    excluded = sorted(
        c.name
        for c in table.columns
        if c.name in HOUSEKEEPING_COLUMNS or c.name.endswith(HOUSEKEEPING_SUFFIXES)
    )
    inner = ",".join(f'"{name}"' for name in excluded)
    return f"'{{{inner}}}'"


def _quoted(expr: str) -> str:
    """A SQL expression as a trigger-argument string literal."""
    return "'" + expr.replace("'", "''") + "'"


def _trigger_block(spec: CaptureSpec) -> str:
    source = event_source(spec.table)
    # A polymorphic facet resolves its type per row; everything else names one
    # constant, and passing that as a literal keeps the extra EXECUTE off the
    # write path of every other table.
    type_expr = spec.resource_type_expr
    static_type = "" if type_expr is not None else spec.static_resource_type
    return "\n".join(
        [
            f"DROP TRIGGER IF EXISTS {spec.trigger_name} ON {spec.table};",
            f"CREATE TRIGGER {spec.trigger_name}",
            f"  AFTER INSERT OR UPDATE OR DELETE ON {spec.table}",
            f"  FOR EACH ROW EXECUTE FUNCTION {CAPTURE_FUNCTION}(",
            f"    {_quoted(initiative_locator(spec.table)(ROW))},",
            f"    '{static_type}',",
            f"    {_quoted(spec.resource_id_expr)},",
            f"    '{spec.facet or ''}',",
            f"    {_housekeeping_literal(spec.table)},",
            f"    '{'guild' if source.guild_wide else ''}',",
            f"    {_quoted(type_expr or '')}",
            "  );",
        ]
    )


_HEADER = """\
-- ============================================================================
-- CHANGE CAPTURE — GENERATED, DO NOT EDIT BY HAND
-- RENDERED AT RUNTIME from app/db/event_capture.py.
--
-- One trigger per evented content table, all calling public.capture_change().
-- Per-table knowledge is passed as trigger arguments derived from
-- INITIATIVE_PATHS (which initiative a row belongs to), the model metadata
-- (which resource an event names), and EVENT_SOURCES (the deviations from
-- those), so a new content table is captured without a second declaration.
--
-- The outbox carries identifiers and changed column NAMES only. Values are read
-- back through the REST API, where the six gates apply to the read.
-- ============================================================================"""


def render_guild_capture_ddl() -> str:
    """Per-table trigger DDL, applied inside each guild schema."""
    blocks = [_trigger_block(spec) for spec in build_specs()]
    return _HEADER + "\n\n" + "\n\n".join(blocks) + "\n"
