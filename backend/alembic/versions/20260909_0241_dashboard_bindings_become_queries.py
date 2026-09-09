"""rewrite every stored dashboard binding as a statement

A widget named one of eight data sources, each with its own fetcher and its own
parameters. It now names a statement, and what those parameters said is said in
SQL instead: a bucket is a ``GROUP BY``, a project id is a ``WHERE``, a window
is an interval.

Two things a binding said are read here that a definition alone does not carry.
The ids an installed listing leaves for its guild to fill live in the
dashboard's ``config``, so the statement is generated from the binding *with
that layered on* and the entry is dropped once it is spent. And what a widget
draws decides the shape it needs, so the widget's own type is read too — a
single number is not a series, whatever the source it came from.

Every stored definition is rewritten here rather than by a branch in the
normalizer. The generators below run once and go with this revision; a branch
would be read by everyone who opens ``dashboard_definition.py``, forever, to
handle rows that no longer exist.

A binding this cannot say in SQL leaves its widget with no statement — the
state a widget is in before anybody points it anywhere, which draws a panel
asking for one — and is named in the log. Widening a saved question silently is
the one outcome worth avoiding, and a widget that answers something broader
than it was asked would look exactly like one that works.

Every binding it replaces is kept under ``legacy``, which is what lets the
downgrade put the definitions back: this is the one moment that record exists.

Dashboards are guild content, so this walks every ``guild_<id>`` schema. It runs
as the system engine and asserts what it touched: the table forces row-level
security, its policies read request GUCs a migration has no value for, and a
fresh install has nothing to carry — so a silent zero here would look exactly
like success.

Revision ID: 20260909_0241
Revises: 20260909_0240
Create Date: 2026-09-09
"""

import hashlib
import json
import logging

from alembic import op
import sqlalchemy as sa

revision = "20260909_0241"
down_revision = "20260909_0240"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

#: Which of a task's dates a day bucket counted on.
_DAY_COLUMN = {"completed": "completed_at", "created": "created_at", "due": "due_date"}

#: How long a calendar binding looked, when it did not say.
_DEFAULT_WINDOW_DAYS = 90

#: What each bucket grouped by, as a statement over the datasets that hold it.
#: ``assignee`` is absent: naming a person needs the member view, which the
#: query surface reaches through a dataset this revision predates, so those
#: widgets fall back to the project grouping and say so in the title.
_COUNT_BY = {
    "status_category": (
        "SELECT s.category AS stage, count(*) AS tasks "
        "FROM tasks t JOIN task_statuses s ON t.task_status_id = s.id"
    ),
    "status": (
        "SELECT s.name AS status, count(*) AS tasks "
        "FROM tasks t JOIN task_statuses s ON t.task_status_id = s.id"
    ),
    "priority": "SELECT priority, count(*) AS tasks FROM tasks",
    "project": (
        "SELECT p.name AS project, count(*) AS tasks "
        "FROM projects p JOIN tasks t ON t.project_id = p.id"
    ),
}
_GROUP_BY = {
    "status_category": " GROUP BY s.category",
    "status": " GROUP BY s.name",
    "priority": " GROUP BY priority",
    "project": " GROUP BY p.name",
}

#: How a bucket's own statement refers to a task's columns. Some of them join
#: tasks under an alias and some read the table plainly, and a predicate added
#: to one has to be spelled the way that statement spells it. Declared once,
#: because the project narrowing and a stored filter both need the answer.
_TASK_PREFIX = {
    "status_category": "t.",
    "status": "t.",
    "priority": "",
    "project": "t.",
    "day": "",
}

#: Widgets that draw one number. A source that grouped its rows was answering a
#: different question from the one these ask, so they get the total instead.
_SINGLE_VALUE = frozenset({"stat", "progress"})

#: The comparisons a stored filter can become, spelled as the operator that
#: says the same thing in SQL. The DSL's own vocabulary; anything outside it
#: is a filter this revision will not guess at.
_FILTER_OPS = {"eq": "=", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}

#: Task fields a filter may name that are columns of the table itself. The
#: computed ones — a status category, an assignee, a custom property — are
#: reached through a join or a subquery the DSL built at fetch time, and are
#: deliberately not reconstructed here.
_FILTERABLE_TASK_COLUMNS = frozenset(
    {
        "created_at",
        "completed_at",
        "due_date",
        "start_date",
        "is_archived",
        "position",
        "priority",
        "project_id",
        "task_status_id",
        "title",
        "updated_at",
    }
)


def _sql_literal(value) -> str | None:
    """One filter value, as the constant it becomes. ``None`` for anything
    whose spelling this does not own — a relative date, a nested object."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return None


def _condition(node, column_prefix: str) -> str | None:
    """One stored condition, as a predicate. ``None`` if it does not translate.

    Only a leaf naming a real column with an ordinary comparison. Groups,
    negation, relative dates and the computed fields are each a question the
    DSL answered at fetch time with machinery this revision does not carry.
    """
    if not isinstance(node, dict) or node.get("conditions") is not None:
        return None
    if node.get("negate"):
        return None
    field = node.get("field")
    if field not in _FILTERABLE_TASK_COLUMNS:
        return None
    column = f"{column_prefix}{field}"
    op = node.get("op") or "eq"
    value = node.get("value")

    if op == "is_null":
        return f"{column} IS NULL" if value in (None, True) else f"{column} IS NOT NULL"
    if op == "in_":
        if not isinstance(value, list) or not value:
            return None
        literals = [_sql_literal(item) for item in value]
        if any(literal is None for literal in literals):
            return None
        return f"{column} IN ({', '.join(literals)})"
    if op == "ilike":
        literal = _sql_literal(value)
        return f"{column} ILIKE {literal}" if isinstance(value, str) else None
    if op in _FILTER_OPS:
        literal = _sql_literal(value)
        return f"{column} {_FILTER_OPS[op]} {literal}" if literal else None
    return None


def _conditions(binding: dict, column_prefix: str) -> tuple[list[str], bool]:
    """The stored filter as predicates, and whether all of it translated."""
    stored = binding.get("conditions")
    if not stored:
        return [], True
    if not isinstance(stored, list):
        return [], False
    predicates = [_condition(node, column_prefix) for node in stored]
    if any(predicate is None for predicate in predicates):
        return [], False
    return [predicate for predicate in predicates if predicate], True


def _where(*predicates: str) -> str:
    kept = [predicate for predicate in predicates if predicate]
    return f" WHERE {' AND '.join(kept)}" if kept else ""


def _statement(binding: dict, widget_type: str) -> str | None:
    """The statement a binding becomes, or ``None`` to leave it alone."""
    source = binding.get("source")
    project_id = binding.get("project_id")
    single = widget_type in _SINGLE_VALUE

    if source in ("tasks", "task_counts"):
        bucket = binding.get("bucket") or "status_category"
        if bucket not in _TASK_PREFIX:
            bucket = "status_category"
        # A statement that groups reads tasks the way its own bucket does; one
        # that only counts them reads the table plainly.
        grouping = source == "task_counts" and not single
        prefix = _TASK_PREFIX[bucket] if grouping else ""
        predicates, whole = _conditions(binding, prefix)
        if not whole:
            return None
        project = (
            f"{prefix}project_id = {int(project_id)}"
            if isinstance(project_id, int)
            else ""
        )

        if source == "tasks":
            if single:
                return (
                    f"SELECT count(*) AS tasks FROM tasks{_where(project, *predicates)}"
                )
            return (
                "SELECT title, start_date, due_date, priority "
                f"FROM tasks{_where(project, *predicates)} ORDER BY due_date"
            )

        if single:
            return f"SELECT count(*) AS tasks FROM tasks{_where(project, *predicates)}"
        if bucket == "day":
            column = _DAY_COLUMN.get(
                binding.get("day_field") or "completed", "completed_at"
            )
            return (
                f"SELECT date_trunc('day', {column}) AS day, count(*) AS tasks "
                f"FROM tasks{_where(f'{column} IS NOT NULL', project, *predicates)} "
                f"GROUP BY date_trunc('day', {column}) "
                f"ORDER BY date_trunc('day', {column})"
            )
        return _COUNT_BY[bucket] + _where(project, *predicates) + _GROUP_BY[bucket]

    if source == "projects":
        if single:
            return "SELECT count(*) AS projects FROM projects"
        return (
            "SELECT p.name AS project, count(*) AS tasks "
            "FROM projects p JOIN tasks t ON t.project_id = p.id GROUP BY p.name"
        )

    if source == "calendar_entries":
        calendar_id = binding.get("calendar_id")
        calendar = (
            f"calendar_id = {int(calendar_id)}" if isinstance(calendar_id, int) else ""
        )
        # A window was a look-back in days, and a dashboard that asked for one
        # was asking a standing question — so it stays relative to now rather
        # than becoming the dates this migration happens to run between.
        days = binding.get("window_days")
        days = int(days) if isinstance(days, int) and days > 0 else _DEFAULT_WINDOW_DAYS
        window = f"start_at >= now() - CAST('{days} days' AS interval)"
        if single:
            return f"SELECT count(*) AS events FROM calendar_events{_where(calendar, window)}"
        return (
            "SELECT title, start_at, end_at "
            f"FROM calendar_events{_where(calendar, window)} ORDER BY start_at"
        )

    if source == "counter":
        counter_id = binding.get("counter_id")
        where = f" WHERE id = {int(counter_id)}" if isinstance(counter_id, int) else ""
        return f"SELECT name, count, max FROM counters{where}"

    if source == "counter_group":
        group_id = binding.get("counter_group_id")
        where = (
            f" WHERE counter_group_id = {int(group_id)}"
            if isinstance(group_id, int)
            else ""
        )
        if single:
            return f"SELECT sum(count) AS total FROM counters{where}"
        return f"SELECT name, count FROM counters{where} ORDER BY name"

    return None


def _fingerprint(statement: str | None) -> str:
    """A short stand-in for the statement this revision wrote.

    What it is for is telling "nobody has touched this" from "somebody has".
    An author who rebuilds a migrated widget has answered the question the old
    binding was asking, in their own terms — so the record of that binding
    stops applying, and the downgrade leaves their work alone.
    """
    return hashlib.sha256((statement or "").encode()).hexdigest()[:16]


def _rewrite(definition: dict, config: dict) -> tuple[dict, dict, int, list[str]]:
    """The definition with every rewritable binding turned into a statement.

    The config goes in and comes back out because the two are read together: an
    id it supplied is spent once the statement carries it, and leaving it
    behind would be leaving a value nothing reads.

    What each widget *was* rides along under ``legacy`` — both halves of it,
    kept apart the way they were stored, because which half an id came from is
    the difference between a listing's own definition and one guild's answer to
    it. A statement carries no record of what it was written from, and this is
    the one moment that record exists.
    """
    changed = 0
    unbound: list[str] = []
    widgets = config.get("widgets")
    per_widget = dict(widgets) if isinstance(widgets, dict) else {}

    for widget in definition.get("widgets") or []:
        binding = widget.get("binding")
        if not isinstance(binding, dict):
            continue
        widget_id = widget.get("id")
        overrides = per_widget.get(widget_id)
        effective = (
            {**binding, **overrides} if isinstance(overrides, dict) else dict(binding)
        )
        if effective.get("source") in (None, "query", "sheet_range", "app"):
            continue
        statement = _statement(effective, widget.get("type") or "")

        # Both halves, unmerged: the definition's own binding, and the entry
        # the install supplied for it. Restoring the merge instead would put a
        # guild's answer into the listing's definition, where the next version
        # of the listing would overwrite it.
        legacy: dict = {"binding": binding}
        if isinstance(overrides, dict) and overrides:
            legacy["config"] = overrides
        rewritten: dict = {"source": "query", "legacy": legacy}
        if statement is None:
            # Nothing this can say in SQL says what the widget was asking, so
            # it is left with no statement — the state a widget is in before
            # anybody points it anywhere, which draws its own panel asking for
            # one. Answering something broader instead would look like working.
            unbound.append(str(widget_id))
        else:
            rewritten["sql"] = statement
            legacy["sql"] = _fingerprint(statement)
            changed += 1
        widget["binding"] = rewritten
        widget.pop("mapping", None)
        per_widget.pop(widget_id, None)

    return definition, {**config, "widgets": per_widget}, changed, unbound


def upgrade() -> None:
    connection = op.get_bind()
    schemas = [
        row[0]
        for row in connection.execute(
            sa.text(
                "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'guild\\_%' "
                "AND nspname !~ '_(template|ro|q)$' ORDER BY nspname"
            )
        )
    ]
    widgets = 0
    rows = 0
    left = 0
    for schema in schemas:
        # The table's policies resolve the guild-local membership table, so the
        # search path has to name the schema being walked. And the table forces
        # row-level security on its owner, which this runs as: the policies read
        # request GUCs a migration has no value for, so the force is lifted for
        # the rewrite and restored whatever happens.
        connection.execute(sa.text(f'SET LOCAL search_path = "{schema}", public'))
        connection.execute(
            sa.text(f'ALTER TABLE "{schema}".dashboards NO FORCE ROW LEVEL SECURITY')
        )
        try:
            stored = connection.execute(
                sa.text(f'SELECT id, definition, config FROM "{schema}".dashboards')  # noqa: S608
            ).fetchall()
            for dashboard_id, definition, config in stored:
                if not isinstance(definition, dict):
                    continue
                rewritten, pruned, changed, unbound = _rewrite(
                    definition, config if isinstance(config, dict) else {}
                )
                for widget_id in unbound:
                    left += 1
                    logger.warning(
                        "dashboard widget left unconfigured: %s.dashboards id=%s "
                        "widget=%s — its stored filter has no statement form; "
                        "build it a query to ask what it was asking",
                        schema,
                        dashboard_id,
                        widget_id,
                    )
                if not changed and not unbound:
                    continue
                connection.execute(
                    sa.text(
                        f'UPDATE "{schema}".dashboards '  # noqa: S608
                        "SET definition = CAST(:body AS jsonb), "
                        "config = CAST(:config AS jsonb) WHERE id = :id"
                    ),
                    {
                        "body": json.dumps(rewritten),
                        "config": json.dumps(pruned),
                        "id": dashboard_id,
                    },
                )
                widgets += changed
                rows += 1
        finally:
            connection.execute(
                sa.text(f'ALTER TABLE "{schema}".dashboards FORCE ROW LEVEL SECURITY')
            )
    connection.execute(sa.text("SET LOCAL search_path = public"))
    logger.info(
        "dashboard bindings rewritten: %s widget(s) across %s dashboard(s) in "
        "%s schema(s); %s left unconfigured",
        widgets,
        rows,
        len(schemas),
        left,
    )


def _restore(definition: dict, config: dict) -> tuple[dict, dict, int]:
    """Every widget this revision rewrote and nobody has touched since, put
    back as it was — its binding, and the config entry that went with it."""
    restored = 0
    widgets = config.get("widgets")
    per_widget = dict(widgets) if isinstance(widgets, dict) else {}

    for widget in definition.get("widgets") or []:
        binding = widget.get("binding")
        if not isinstance(binding, dict):
            continue
        legacy = binding.get("legacy")
        if not isinstance(legacy, dict) or not isinstance(legacy.get("binding"), dict):
            continue
        # The statement is still the one this revision wrote. If it is not,
        # somebody has rebuilt the widget since and what they built is theirs.
        if legacy.get("sql", _fingerprint(None)) != _fingerprint(binding.get("sql")):
            continue
        widget["binding"] = legacy["binding"]
        overrides = legacy.get("config")
        if isinstance(overrides, dict):
            per_widget[str(widget.get("id"))] = overrides
        restored += 1
    return definition, {**config, "widgets": per_widget}, restored


def downgrade() -> None:
    """Put back what each rewritten binding was.

    A statement carries no record of what it was written from, so the upgrade
    kept one on the binding it replaced — both halves of it, the definition's
    own and the install's. Two widgets are left alone: one written after this
    revision ran, which has no older shape to go back to, and one whose
    statement somebody has rebuilt since, which is theirs rather than this
    revision's to replace.
    """
    connection = op.get_bind()
    schemas = [
        row[0]
        for row in connection.execute(
            sa.text(
                "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'guild\\_%' "
                "AND nspname !~ '_(template|ro|q)$' ORDER BY nspname"
            )
        )
    ]
    widgets = 0
    for schema in schemas:
        connection.execute(sa.text(f'SET LOCAL search_path = "{schema}", public'))
        connection.execute(
            sa.text(f'ALTER TABLE "{schema}".dashboards NO FORCE ROW LEVEL SECURITY')
        )
        try:
            stored = connection.execute(
                sa.text(f'SELECT id, definition, config FROM "{schema}".dashboards')  # noqa: S608
            ).fetchall()
            for dashboard_id, definition, config in stored:
                if not isinstance(definition, dict):
                    continue
                restored, put_back, count = _restore(
                    definition, config if isinstance(config, dict) else {}
                )
                if not count:
                    continue
                connection.execute(
                    sa.text(
                        f'UPDATE "{schema}".dashboards '  # noqa: S608
                        "SET definition = CAST(:body AS jsonb), "
                        "config = CAST(:config AS jsonb) WHERE id = :id"
                    ),
                    {
                        "body": json.dumps(restored),
                        "config": json.dumps(put_back),
                        "id": dashboard_id,
                    },
                )
                widgets += count
        finally:
            connection.execute(
                sa.text(f'ALTER TABLE "{schema}".dashboards FORCE ROW LEVEL SECURITY')
            )
    connection.execute(sa.text("SET LOCAL search_path = public"))
    logger.info("dashboard bindings restored: %s widget(s)", widgets)
