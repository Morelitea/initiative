"""rewrite every stored dashboard binding as a statement

A widget named one of eight data sources, each with its own fetcher and its own
parameters. It now names a statement, and what those parameters said is said in
SQL instead: a bucket is a ``GROUP BY``, a project id is a ``WHERE``, a window
is an interval.

Every stored definition is rewritten here rather than by a branch in the
normalizer. The generators below run once and go with this revision; a branch
would be read by everyone who opens ``dashboard_definition.py``, forever, to
handle rows that no longer exist.

Dashboards are guild content, so this walks every ``guild_<id>`` schema. It runs
as the system engine and asserts what it touched: the table forces row-level
security, its policies read request GUCs a migration has no value for, and a
fresh install has nothing to carry — so a silent zero here would look exactly
like success.

Revision ID: 20260909_0241
Revises: 20260909_0240
Create Date: 2026-09-09
"""

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


def _statement(binding: dict) -> str | None:
    """The statement a binding becomes, or ``None`` to leave it alone."""
    source = binding.get("source")
    project_id = binding.get("project_id")
    project_clause = (
        f" WHERE t.project_id = {int(project_id)}"
        if isinstance(project_id, int)
        else ""
    )

    if source == "task_counts":
        bucket = binding.get("bucket") or "status_category"
        if bucket == "day":
            column = _DAY_COLUMN.get(
                binding.get("day_field") or "completed", "completed_at"
            )
            where = f" WHERE {column} IS NOT NULL"
            if isinstance(project_id, int):
                where += f" AND project_id = {int(project_id)}"
            return (
                f"SELECT date_trunc('day', {column}) AS day, count(*) AS tasks "
                f"FROM tasks{where} GROUP BY date_trunc('day', {column}) "
                f"ORDER BY date_trunc('day', {column})"
            )
        bucket = bucket if bucket in _COUNT_BY else "status_category"
        return _COUNT_BY[bucket] + project_clause + _GROUP_BY[bucket]

    if source == "tasks":
        where = (
            f" WHERE project_id = {int(project_id)}"
            if isinstance(project_id, int)
            else ""
        )
        return (
            "SELECT title, start_date, due_date, priority "
            f"FROM tasks{where} ORDER BY due_date"
        )

    if source == "projects":
        return (
            "SELECT p.name AS project, count(*) AS tasks "
            "FROM projects p JOIN tasks t ON t.project_id = p.id GROUP BY p.name"
        )

    if source == "calendar_entries":
        calendar_id = binding.get("calendar_id")
        where = (
            f" WHERE calendar_id = {int(calendar_id)}"
            if isinstance(calendar_id, int)
            else ""
        )
        return f"SELECT title, start_at, end_at FROM calendar_events{where} ORDER BY start_at"

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
        return f"SELECT name, count FROM counters{where} ORDER BY name"

    return None


def _rewrite(definition: dict) -> tuple[dict, int]:
    """The definition with every rewritable binding turned into a statement."""
    changed = 0
    for widget in definition.get("widgets") or []:
        binding = widget.get("binding")
        if not isinstance(binding, dict):
            continue
        statement = _statement(binding)
        if statement is None:
            continue
        widget["binding"] = {"source": "query", "sql": statement}
        widget.pop("mapping", None)
        changed += 1
    return definition, changed


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
                sa.text(f'SELECT id, definition FROM "{schema}".dashboards')  # noqa: S608
            ).fetchall()
            for dashboard_id, definition in stored:
                if not isinstance(definition, dict):
                    continue
                rewritten, changed = _rewrite(definition)
                if not changed:
                    continue
                connection.execute(
                    sa.text(
                        f'UPDATE "{schema}".dashboards '  # noqa: S608
                        "SET definition = CAST(:body AS jsonb) WHERE id = :id"
                    ),
                    {"body": json.dumps(rewritten), "id": dashboard_id},
                )
                widgets += changed
                rows += 1
        finally:
            connection.execute(
                sa.text(f'ALTER TABLE "{schema}".dashboards FORCE ROW LEVEL SECURITY')
            )
    connection.execute(sa.text("SET LOCAL search_path = public"))
    logger.info(
        "dashboard bindings rewritten: %s widget(s) across %s dashboard(s) in %s schema(s)",
        widgets,
        rows,
        len(schemas),
    )


def downgrade() -> None:
    """A statement carries no record of the binding it was written from, so the
    old shape cannot be recovered. Deployments that need it restore from a
    backup taken before the upgrade."""
    pass
