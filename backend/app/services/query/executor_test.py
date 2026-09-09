"""Running a query, and the limits it runs inside.

These go to a real database: the interesting behaviour is Postgres's, not
ours — a transaction that refuses a write, a role that holds only SELECT, a
planner estimate, a statement timeout.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.messages import QueryMessages
from app.db.schema_provisioning import drop_guild_schema, provision_guild_schema
from app.services.query import QueryError, execute, resolve, run

pytestmark = pytest.mark.database

_GID = 990_200


@pytest.fixture
async def guild(engine):
    async with engine.begin() as conn:
        await provision_guild_schema(conn, _GID)
    try:
        yield _GID
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID)


async def test_it_returns_columns_and_rows(guild):
    result = await run(
        "SELECT title FROM tasks", guild_id=guild, user_id=1, guild_role="admin"
    )
    assert result.columns == ("title",)
    assert result.rows == ()


async def test_an_aggregate_answers_without_shipping_the_rows(guild):
    """The shape a stat tile asks for: one number, computed by the database."""
    result = await run(
        "SELECT count(*) AS n FROM tasks",
        guild_id=guild,
        user_id=1,
        guild_role="admin",
    )
    assert result.columns == ("n",)
    assert result.rows == ({"n": 0},)


async def test_it_reports_what_the_planner_expected(guild):
    result = await run(
        "SELECT title FROM tasks", guild_id=guild, user_id=1, guild_role="admin"
    )
    assert result.cost > 0


async def test_a_statement_the_planner_prices_too_high_never_runs(guild, monkeypatch):
    monkeypatch.setattr(settings, "QUERY_MAX_COST", 0.0)
    with pytest.raises(QueryError) as refused:
        await run(
            "SELECT title FROM tasks", guild_id=guild, user_id=1, guild_role="admin"
        )
    assert refused.value.code == QueryMessages.TOO_EXPENSIVE


async def test_a_slow_statement_is_stopped(guild, monkeypatch):
    """The time bound, exercised through the one function that can spend it."""
    monkeypatch.setattr(settings, "QUERY_STATEMENT_TIMEOUT_MS", 100)
    statement = resolve("SELECT title FROM tasks")
    slow = type(statement)(
        sql="SELECT pg_sleep(3) AS slept", parameters=(), relations=("tasks",)
    )
    with pytest.raises(QueryError) as stopped:
        await execute(slow, guild_id=guild, user_id=1, guild_role="admin")
    assert stopped.value.code == QueryMessages.TIMED_OUT


async def test_the_transaction_refuses_a_write(guild):
    """Reached past the validator on purpose: the transaction and the role
    answer for themselves, so a statement that never went through resolve is
    still refused."""
    statement = resolve("SELECT title FROM tasks")
    write = type(statement)(
        sql=f"INSERT INTO guild_{_GID}.tasks (title) VALUES ('x')",
        parameters=(),
        relations=("tasks",),
    )
    with pytest.raises(Exception) as refused:
        await execute(write, guild_id=guild, user_id=1, guild_role="admin")
    assert (
        "read-only" in str(refused.value).lower()
        or "permission" in str(refused.value).lower()
    )


async def test_more_rows_than_one_query_returns_are_cut_off(guild, monkeypatch):
    monkeypatch.setattr(settings, "QUERY_MAX_ROWS", 2)
    statement = resolve("SELECT title FROM tasks")
    many = type(statement)(
        sql="SELECT g AS n FROM generate_series(1, 50) AS g",
        parameters=(),
        relations=("tasks",),
    )
    result = await execute(many, guild_id=guild, user_id=1, guild_role="admin")
    assert len(result.rows) == 2
    assert result.truncated is True


async def test_a_guild_runs_only_so_many_at_once(guild, monkeypatch):
    """The cap is per guild, so one community's queries wait for each other
    rather than for everybody's."""
    import asyncio

    monkeypatch.setattr(settings, "QUERY_MAX_CONCURRENT_PER_GUILD", 1)
    monkeypatch.setattr(settings, "QUERY_POOL_TIMEOUT_SECONDS", 1)
    from app.services.query import executor

    executor._in_flight.pop(guild, None)
    statement = resolve("SELECT title FROM tasks")
    slow = type(statement)(
        sql="SELECT pg_sleep(2) AS slept", parameters=(), relations=("tasks",)
    )
    held = asyncio.create_task(
        execute(slow, guild_id=guild, user_id=1, guild_role="admin")
    )
    await asyncio.sleep(0.3)
    try:
        with pytest.raises(QueryError) as busy:
            await run(
                "SELECT title FROM tasks",
                guild_id=guild,
                user_id=1,
                guild_role="admin",
            )
        assert busy.value.code == QueryMessages.BUSY
    finally:
        held.cancel()
        with pytest.raises(BaseException):
            await held
        executor._in_flight.pop(guild, None)
