"""archiving becomes one timestamp, on everything that can be finished with

``is_archived`` was a boolean on three tables, and ``projects`` carried
``archived_at`` beside it — two columns for one fact, kept in step by hand.
Both become a single nullable ``archived_at``: null while live, stamped when it
happens, the same shape ``deleted_at`` already has. It answers "when" as well as
"whether", which is what the project screen was already showing and what a task
and an initiative could not say at all.

It also reaches every tool. Anything an initiative offers can be finished with,
so documents, queues, counter groups, calendars, dashboards, posts and galleries
gain the column here; before this, only projects, tasks and initiatives could be
put away.

Guild content, so this walks ``guild_template`` and every ``guild_<id>``. The
existing flags are carried onto the new column before the old one goes, and the
count is asserted: these tables force row-level security, their policies read
request GUCs a migration has no value for, and a fresh install has nothing to
carry — so a silent zero here would look exactly like success. The force is
lifted for the carry and restored whatever happens.

``archived_at`` is stamped from ``updated_at`` where only the boolean was
recorded. It is the closest honest answer: nothing wrote down when those rows
were archived, and inventing ``now()`` would date every one of them to the
upgrade.

The row guards naming ``is_archived`` in their WHEN clause are dropped so the
column can go. Provisioning re-renders them from the registry on the next boot,
which is the ordinary path for a registry change and runs in this same start-up.

Revision ID: 20260911_0255
Revises: 20260911_0254
Create Date: 2026-09-11
"""

import json
import logging
from typing import Any

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20260911_0255"
down_revision = "20260911_0254"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

#: Tools that could not be archived before, plus the two non-tools that could
#: only say whether. ``projects`` is absent: it already has the column.
_GAINING_COLUMN = (
    "documents",
    "queues",
    "counter_groups",
    "calendars",
    "dashboards",
    "posts",
    "galleries",
    "tasks",
    "initiatives",
)

#: The three that carried ``is_archived``, and whose rows have to be carried.
_CARRYING = ("projects", "tasks", "initiatives")


#: Saved filters name their field. A boolean asked "is it archived"; a
#: timestamp asks "is it set", so a stored condition is carried across rather
#: than left naming a field that no longer exists.
_SAVED_FILTERS: tuple[tuple[str, str], ...] = (
    ("project_filter_presets", "filters"),
    ("dashboards", "definition"),
    ("dashboards", "config"),
)


def _carry_condition(node: Any) -> Any:
    """Rewrite ``is_archived eq <bool>`` wherever it appears in a saved body.

    ``is_null`` carries whether it means null or not-null, so "not archived"
    becomes "archived_at is null" and the pair stays the same question.
    """
    if isinstance(node, dict):
        if node.get("field") == "is_archived" and node.get("op") == "eq":
            return {
                **node,
                "field": "archived_at",
                "op": "is_null",
                "value": not bool(node.get("value")),
            }
        return {key: _carry_condition(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_carry_condition(item) for item in node]
    return node


def _carry_saved_filters(connection, schema: str) -> int:
    """Walk the saved bodies of one guild schema, rewriting what names the old
    field. Force is lifted for the writes and restored whatever happens."""
    carried = 0
    for table, column in _SAVED_FILTERS:
        rows = connection.execute(
            sa.text(
                f"SELECT id, {column} FROM {table} "  # noqa: S608 — literals above
                f"WHERE {column}::text LIKE '%is_archived%'"
            )
        ).all()
        if not rows:
            continue
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        try:
            for row_id, body in rows:
                rewritten = _carry_condition(body)
                if rewritten == body:
                    continue
                connection.execute(
                    sa.text(
                        f"UPDATE {table} SET {column} = :body "  # noqa: S608
                        "WHERE id = :id"
                    ),
                    {"body": json.dumps(rewritten), "id": row_id},
                )
                carried += 1
        finally:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    return carried


def _route(connection, schema: str) -> None:
    connection.execute(
        sa.text("SELECT set_config('search_path', :sp, true)"),
        {"sp": f'"{schema}", public'},
    )


def upgrade() -> None:
    connection = op.get_bind()
    carried_total = 0
    filters_carried = 0

    for schema in guild_schema_names(connection):
        _route(connection, schema)

        for table in _GAINING_COLUMN:
            op.execute(f"ALTER TABLE {table} ADD COLUMN archived_at timestamptz")

        for table in _CARRYING:
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        try:
            for table in _CARRYING:
                expected = connection.execute(
                    sa.text(
                        f"SELECT count(*) FROM {table} "  # noqa: S608 — literal above
                        "WHERE is_archived AND archived_at IS NULL"
                    )
                ).scalar_one()
                carried = connection.execute(
                    sa.text(
                        f"UPDATE {table} SET archived_at = updated_at "  # noqa: S608
                        "WHERE is_archived AND archived_at IS NULL"
                    )
                ).rowcount
                if carried != expected:
                    raise RuntimeError(
                        f"{schema}.{table}: {expected} archived row(s) to carry but "
                        f"{carried} were written — the carry did not reach every row"
                    )
                carried_total += carried
        finally:
            for table in _CARRYING:
                op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

        # These name the column in their WHEN clause, so it cannot be dropped
        # while they stand. Re-rendered from the registry on the next boot.
        for table in _CARRYING:
            op.execute(f"DROP TRIGGER IF EXISTS tr_{table}_frozen_guard ON {table}")

        for table in _CARRYING:
            op.execute(f"ALTER TABLE {table} DROP COLUMN is_archived")

        # The index went with the column it named; the same shape on the new one.
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_project_archived "
            "ON tasks (project_id, archived_at)"
        )

        filters_carried += _carry_saved_filters(connection, schema)

    connection.execute(sa.text("SET LOCAL search_path = public"))
    logger.info(
        "archive flags carried onto archived_at: %s row(s); "
        "saved filters rewritten: %s",
        carried_total,
        filters_carried,
    )


def downgrade() -> None:
    connection = op.get_bind()

    for schema in guild_schema_names(connection):
        _route(connection, schema)

        for table in _CARRYING:
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN is_archived boolean NOT NULL "
                "DEFAULT false"
            )
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            try:
                connection.execute(
                    sa.text(
                        f"UPDATE {table} SET is_archived = true "  # noqa: S608
                        "WHERE archived_at IS NOT NULL"
                    )
                )
            finally:
                op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

        # Every table about to lose the column has a guard naming it.
        for table in _GAINING_COLUMN:
            op.execute(f"DROP TRIGGER IF EXISTS tr_{table}_frozen_guard ON {table}")

        # ``projects`` keeps its ``archived_at``: it had one before this ran.
        for table in _GAINING_COLUMN:
            op.execute(f"ALTER TABLE {table} DROP COLUMN archived_at")

        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_project_archived "
            "ON tasks (project_id, is_archived)"
        )

    connection.execute(sa.text("SET LOCAL search_path = public"))
