"""What a community costs the database, held where it was measured.

Each check is a count or a size Postgres reports, not a time, so it says the
same thing on every run. They are deselected by default and run nightly on the
PostgreSQL the example deployment ships (``pytest -m budget``): a schema's
memory differs between major versions. When a change lowers a number, lower
its budget with it.
"""

import json

import asyncpg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import establish_guild_access
from app.db.authorization import GUILD_FUNCTION_SIGNATURES, READ_FUNCTIONS
from app.db.schema_provisioning import guild_role_name, guild_schema_name
from app.models.platform.guild import CommunityRole
from app.models.tenant.task import Task
from app.schemas.query import FilterOp
from app.services.tenant import properties as properties_service
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_property_definition,
    create_task,
    create_user,
    route_session_to_guild,
)

from conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.budget

#: Parsed policies, per community, per database connection that has served it.
#: Postgres keeps them until the table changes, so a pooled connection holds one
#: of these for every community it has served. 5.0 MB on 2026-10-01.
POLICY_MEMORY_PER_COMMUNITY = 5_500 * 1024

#: The same for one table. 240 KB (``task_assignees``) on 2026-10-01.
POLICY_MEMORY_PER_TABLE = 280 * 1024

_POLICY_MEMORY = (
    "SELECT ident, total_bytes FROM pg_backend_memory_contexts "
    "WHERE name = 'row security descriptor'"
)


async def test_a_communitys_policies_fit_their_memory(session: AsyncSession):
    guild = await create_guild(session)
    await session.commit()
    schema = guild_schema_name(guild.id)

    # A connection of its own, so nothing another test loaded is counted.
    conn = await asyncpg.connect(TEST_DATABASE_URL.replace("+asyncpg", "", 1))
    try:
        tables = await conn.fetch(
            "SELECT c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = $1 AND c.relkind IN ('r', 'p')",
            schema,
        )
        for (table,) in tables:
            await conn.execute(f'SELECT 1 FROM "{schema}"."{table}" LIMIT 0')
        loaded = await conn.fetch(_POLICY_MEMORY)
    finally:
        await conn.close()

    total = sum(row["total_bytes"] for row in loaded)
    assert total <= POLICY_MEMORY_PER_COMMUNITY, (
        f"a community's policies take {total / 1048576:.2f} MB per connection, "
        f"over {POLICY_MEMORY_PER_COMMUNITY / 1048576:.2f} MB"
    )
    heaviest = max(loaded, key=lambda row: row["total_bytes"])
    assert heaviest["total_bytes"] <= POLICY_MEMORY_PER_TABLE, (
        f"{heaviest['ident']}'s policies take {heaviest['total_bytes'] // 1024} KB, "
        f"over {POLICY_MEMORY_PER_TABLE // 1024} KB"
    )


async def test_the_gates_that_read_the_standing_keep_their_plans(
    session: AsyncSession,
):
    """A ``LANGUAGE sql`` function that is not inlined is planned again on every
    query that calls it; a ``plpgsql`` one keeps its plan for the session."""
    guild = await create_guild(session)
    await session.commit()
    schema = guild_schema_name(guild.id)
    gates = [
        f"{schema}.{name}{args}"
        for name, args in GUILD_FUNCTION_SIGNATURES.items()
        if name == "current_standing"
        or name in dict(READ_FUNCTIONS)
        or "public.standing" in args
    ]

    languages = dict(
        (
            await session.exec(
                text(
                    "SELECT p.oid::regprocedure::text, l.lanname "
                    "FROM pg_proc p JOIN pg_language l ON l.oid = p.prolang "
                    "WHERE p.oid = ANY(CAST(:gates AS regprocedure[]))"
                ).bindparams(gates=gates)
            )
        ).all()
    )

    assert len(languages) == len(gates)
    assert {name: lang for name, lang in languages.items() if lang != "plpgsql"} == {}


async def test_the_standing_is_read_once_a_statement(session: AsyncSession):
    """Every policy passes ``(SELECT current_standing())`` and reads each
    field as ``(SELECT standing_<field>())``, which Postgres runs once for the
    statement. Called bare, either would run once a row."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    rows = 12
    for _ in range(rows):
        await create_project(session, initiative, owner)
    await session.commit()
    schema = guild_schema_name(guild.id)

    for statement in (
        "SET LOCAL track_functions = 'pl'",
        f'SET LOCAL ROLE "{guild_role_name(guild.id)}"',
    ):
        await session.exec(text(statement))
    await session.exec(text(f'SELECT count(*) FROM "{schema}".projects'))
    await session.exec(text("RESET ROLE"))
    calls = dict(
        (
            await session.exec(
                text(
                    "SELECT p.proname, pg_stat_get_xact_function_calls(p.oid)"
                    " FROM pg_proc p WHERE p.pronamespace = CAST(:s AS regnamespace)"
                    " AND p.proname = ANY(:names)"
                ).bindparams(
                    s=schema,
                    names=["current_standing", *dict(READ_FUNCTIONS)],
                )
            )
        ).all()
    )
    await session.rollback()

    ran = {name: n for name, n in calls.items() if n}
    assert "current_standing" in ran and set(ran) - {"current_standing"}, ran
    assert all(n < rows for n in ran.values()), f"reading {rows} projects ran {ran}"


def _rows_read(plan: dict, relation: str) -> int:
    """Rows a plan read from ``relation``, kept or filtered out, over every loop."""
    read = 0
    if plan.get("Relation Name") == relation:
        kept = plan.get("Actual Rows", 0) + plan.get("Rows Removed by Filter", 0)
        read += kept * plan.get("Actual Loops", 1)
    for child in plan.get("Plans", []):
        read += _rows_read(child, relation)
    return read


async def _many_tasks(session: AsyncSession, project, count: int) -> None:
    """``count`` tasks in ``project``, copied from one in a statement: a
    planner choosing between scans needs the volume a real community has."""
    seed = await create_task(session, project)
    columns = ", ".join(
        f'"{name}"'
        for (name,) in (
            await session.exec(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'tasks' "
                    "AND column_name <> 'id' AND is_generated = 'NEVER'"
                )
            )
        ).all()
    )
    await session.exec(
        text(
            f"INSERT INTO tasks ({columns}) SELECT {columns} FROM tasks, "  # noqa: S608
            "generate_series(2, :count) WHERE id = :seed"
        ).bindparams(count=count, seed=seed.id)
    )


async def test_a_property_filter_reads_only_the_listed_rows_values(
    acting_user, session: AsyncSession, role_session
):
    """Filtering one project's tasks reads the values of that project's tasks,
    not every value of the property in the community. Each value read is a
    read the policy authorizes, so a filter that read them all would cost a
    small list as much as the largest one."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    small = await create_project(session, a.initiative, a.user)
    stage = await create_property_definition(session, a.initiative, name="Stage")
    await route_session_to_guild(session, a.guild.id)
    await _many_tasks(session, a.project, 2000)
    await _many_tasks(session, small, 3)
    await session.exec(
        text(
            "INSERT INTO property_values "
            "(entity_type, entity_id, property_id, value_text, created_at, updated_at) "
            "SELECT 'task', id, :stage, 'live', now(), now() FROM tasks"
        ).bindparams(stage=stage.id)
    )
    await session.commit()
    await route_session_to_guild(session, a.guild.id)
    for table in ("tasks", "property_values"):
        await session.exec(text(f"ANALYZE {table}"))
    await session.commit()

    member = await role_session("app_user")
    await establish_guild_access(member, a.user, a.guild.id)
    for op, value in ((FilterOp.eq, "live"), (FilterOp.is_null, True)):
        clause = properties_service.build_single_property_clause(
            "task", stage.id, op, value, stage
        )
        query = (
            select(func.count())
            .select_from(Task)
            .where(Task.project_id == small.id, clause)
        )
        sql = str(
            query.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        (plan,) = (
            await member.exec(text(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}"))
        ).one()
        plan = plan if isinstance(plan, list) else json.loads(plan)
        read = _rows_read(plan[0]["Plan"], "property_values")
        assert read <= 3, f"{op.value} on 3 tasks read {read} values"
