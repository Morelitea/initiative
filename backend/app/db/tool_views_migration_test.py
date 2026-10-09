"""Migration 20261009_0477 turns a project's filter presets into its views.
Loaded by path and run on a guild the test builds, the way
``file_versions_by_pointer_migration_test`` runs its revision: down to the old
shape, rows written as an older release wrote them, up, and down again."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.testing import create_guild, create_initiative, create_project, create_user

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261009_0477_tool_views.py"
)


def _load():
    spec = importlib.util.spec_from_file_location(_MIGRATION.stem, _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SEEDS = (
    ("all", "All", True, "{}"),
    (
        "incomplete",
        "Incomplete",
        False,
        '{"status_categories": ["backlog", "todo", "in_progress"]}',
    ),
    ("unassigned", "Unassigned", False, '{"assignees": ["none"]}'),
    ("mine", "Mine", False, '{"assignees": ["me"]}'),
)
_TABLE = {"layout": {"type": "table"}}
_BOARD = {"layout": {"type": "board"}}
_CALENDAR = {"layout": {"type": "calendar"}}
_INCOMPLETE = {
    "layout": {"type": "table"},
    "filters": {"status_categories": ["backlog", "todo", "in_progress"]},
}
_UNASSIGNED = {"layout": {"type": "table"}, "filters": {"assignees": ["none"]}}
_MINE = {"layout": {"type": "table"}, "filters": {"assignees": ["me"]}}


async def test_presets_become_views_and_come_back(session) -> None:
    """A project as it was seeded stores nothing and keeps the shipped views.
    Every other stores the shipped six with its changes: an edited seed in its
    place, a deleted one left out, its own presets after them on its default
    layout, and the default it chose. A preset holding a shipped layout
    view's slug keeps it. The downgrade puts back the presets and re-seeds
    the projects that stored nothing."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    names = ("Seeded", "Table mode", "Edited", "Deleted", "Custom", "Kanban", "Clash")
    projects = {
        name: (await create_project(session, initiative, user, name=name)).id
        for name in names
    }
    migration = _load()

    def run(step):
        def apply(sync_session) -> None:
            bind = sync_session.connection()
            bind.execute(
                text("SELECT set_config('search_path', :sp, true)"),
                {"sp": f"{schema}, public"},
            )
            with Operations.context(MigrationContext.configure(bind)):
                step()

        return apply

    async def sql(statement: str, **params):
        return await (await session.connection()).execute(text(statement), params)

    async def presets(project: str, *rows: tuple[str, str, bool, str]) -> None:
        for position, (slug, name, is_default, filters) in enumerate(rows):
            await sql(
                f"INSERT INTO {schema}.project_filter_presets"
                " (project_id, slug, name, position, is_default, filters,"
                " created_at, updated_at) VALUES"
                " (:p, :slug, :name, :position, :is_default, CAST(:f AS jsonb),"
                " now(), now())",
                p=projects[project],
                slug=slug,
                name=name,
                position=position,
                is_default=is_default,
                f=filters,
            )

    async def mode(project: str, value: str) -> None:
        await sql(
            f"UPDATE {schema}.projects SET default_view_mode = :m WHERE id = :p",
            m=value,
            p=projects[project],
        )

    await session.run_sync(run(migration._apply_downgrade))
    await sql(f"DELETE FROM {schema}.project_filter_presets")
    # Listed out of order: the order of a project's presets is no change.
    await presets("Seeded", *reversed(_SEEDS))
    await presets("Table mode", *_SEEDS)
    await mode("Table mode", "table")
    await presets(
        "Edited",
        _SEEDS[0],
        _SEEDS[1],
        _SEEDS[2],
        ("mine", "My work", False, '{"assignees": ["me"], "due": "overdue"}'),
    )
    await presets("Deleted", _SEEDS[0], _SEEDS[1], _SEEDS[3])
    await presets(
        "Custom",
        *_SEEDS,
        ("blocked", "Blocked", False, '{"tag_ids": [7]}'),
    )
    await mode("Custom", "calendar")
    await presets("Kanban", *_SEEDS)
    await mode("Kanban", "kanban")
    await presets(
        "Clash",
        ("all", "All", False, "{}"),
        *_SEEDS[1:],
        ("board", "Board", True, '{"assignees": ["me"]}'),
    )
    await mode("Clash", "kanban")

    await session.run_sync(run(migration._apply_upgrade))
    rows = (
        await sql(
            f"SELECT tool_id, slug, name, is_default, definition"
            f" FROM {schema}.tool_views ORDER BY tool_id, position"
        )
    ).all()
    stored: dict[int, list[tuple]] = {}
    for row in rows:
        stored.setdefault(row.tool_id, []).append(tuple(row)[1:])
    shipped = [
        ("table", "Table", True, _TABLE),
        ("board", "Board", False, _BOARD),
        ("calendar", "Calendar", False, _CALENDAR),
        ("incomplete", "Incomplete", False, _INCOMPLETE),
        ("unassigned", "Unassigned", False, _UNASSIGNED),
        ("mine", "Mine", False, _MINE),
    ]
    default_board = [
        (slug, name, slug == "board", definition)
        for slug, name, _, definition in shipped
    ]
    assert stored == {
        projects["Edited"]: [
            *shipped[:5],
            (
                "mine",
                "My work",
                False,
                {
                    "layout": {"type": "table"},
                    "filters": {"assignees": ["me"], "due": "overdue"},
                },
            ),
        ],
        projects["Deleted"]: [*shipped[:4], shipped[5]],
        projects["Custom"]: [
            ("table", "Table", False, _TABLE),
            *shipped[1:2],
            ("calendar", "Calendar", True, _CALENDAR),
            *shipped[3:],
            (
                "blocked",
                "Blocked",
                False,
                {"layout": {"type": "calendar"}, "filters": {"tag_ids": [7]}},
            ),
        ],
        projects["Kanban"]: default_board,
        projects["Clash"]: [
            ("table", "Table", False, _TABLE),
            ("board-2", "Board", False, _BOARD),
            *[(slug, name, False, d) for slug, name, _, d in shipped[2:]],
            (
                "board",
                "Board",
                True,
                {"layout": {"type": "board"}, "filters": {"assignees": ["me"]}},
            ),
        ],
    }

    await session.run_sync(run(migration._apply_downgrade))
    back = (
        await sql(
            f"SELECT project_id, slug, name, is_default, filters"
            f" FROM {schema}.project_filter_presets ORDER BY project_id, position"
        )
    ).all()
    restored: dict[int, list[tuple]] = {}
    for row in back:
        restored.setdefault(row.project_id, []).append(tuple(row)[1:])
    seeds = [
        (slug, name, is_default, json.loads(filters))
        for slug, name, is_default, filters in _SEEDS
    ]
    assert restored[projects["Seeded"]] == seeds
    assert restored[projects["Table mode"]] == seeds
    assert restored[projects["Deleted"]] == [seeds[1], seeds[3]]
    assert restored[projects["Clash"]] == [
        *[(slug, name, False, f) for slug, name, _, f in seeds[1:]],
        ("board", "Board", True, {"assignees": ["me"]}),
    ]
    modes = dict(
        (await sql(f"SELECT id, default_view_mode FROM {schema}.projects")).all()
    )
    assert modes[projects["Kanban"]] == "kanban"

    await session.run_sync(run(migration._apply_upgrade))
