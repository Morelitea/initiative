"""What a community costs the database, held where it was measured.

Each check is a count or a size Postgres reports, not a time, so it says the
same thing on every run. They are deselected by default and run nightly on the
PostgreSQL the example deployment ships (``pytest -m budget``): a schema's
memory differs between major versions. When a change lowers a number, lower
its budget with it.
"""

import asyncpg
import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.authorization import GUILD_FUNCTION_SIGNATURES, READ_FUNCTIONS
from app.db.schema_provisioning import guild_role_name, guild_schema_name
from app.testing import create_guild, create_initiative, create_project, create_user

from conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.budget

#: Parsed policies, per community, per database connection that has served it.
#: Postgres keeps them until the table changes, so a pooled connection holds one
#: of these for every community it has served. 5.6 MB on 2026-10-01.
POLICY_MEMORY_PER_COMMUNITY = 6 * 1024 * 1024

#: The same for one table. 304 KB (``task_property_values``) on 2026-10-01.
POLICY_MEMORY_PER_TABLE = 350 * 1024

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
