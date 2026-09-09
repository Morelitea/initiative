"""Run a resolved query, inside everything that bounds it.

A statement arrives here already read, validated and rewritten
(:mod:`app.services.query.resolve`). What happens here is the running of it:
under which role, in which transaction, against which limits.

Five things bound a query, and they are independent of each other:

* a **pool of its own**, so these statements wait for each other rather than
  for the requests serving every other page;
* a **cap per guild** on how many run at once;
* a **read-only transaction**, which refuses a write whatever the statement
  says;
* the **query role**, which holds ``SELECT`` and no more;
* **statement limits** — a time bound, a memory bound, no parallel workers —
  and a **planner estimate** checked before anything runs.

The last one is the only one that can refuse a statement that is otherwise
perfectly legal, and it does so without executing it.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Optional

from asyncpg.exceptions import QueryCanceledError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import QueryMessages
from app.db import session as db_session
from app.db.session import set_rls_context
from app.services.query.resolve import QueryError, ResolvedQuery, resolve


@dataclass(frozen=True)
class QueryResult:
    """What a query returned, and what it cost to say so."""

    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    #: The planner's estimate for the statement that ran.
    cost: float
    #: Whether there were more rows than one query returns.
    truncated: bool


#: One semaphore per guild, made on first use. A guild that has never run a
#: query has no entry; one that has holds an object of a few bytes.
_in_flight: dict[int, asyncio.Semaphore] = {}


def _guild_slot(guild_id: int) -> asyncio.Semaphore:
    slot = _in_flight.get(guild_id)
    if slot is None:
        slot = asyncio.Semaphore(settings.QUERY_MAX_CONCURRENT_PER_GUILD)
        _in_flight[guild_id] = slot
    return slot


async def _bound_transaction(connection: Any) -> None:
    """Put the limits on the transaction, before anything of the reader's runs.

    Issued through SQLAlchemy rather than the driver underneath it, so they
    land inside the transaction it is managing — all four are local to one, and
    ``SET TRANSACTION READ ONLY`` has to be the first thing in it.
    """
    await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    await connection.exec_driver_sql(
        f"SET LOCAL statement_timeout = {int(settings.QUERY_STATEMENT_TIMEOUT_MS)}"
    )
    await connection.exec_driver_sql(
        f"SET LOCAL work_mem = '{settings.QUERY_WORK_MEM}'"
    )
    # One query is one backend's worth of the server's attention.
    await connection.exec_driver_sql("SET LOCAL max_parallel_workers_per_gather = 0")


async def _estimated_cost(connection: Any, statement: ResolvedQuery) -> float:
    plan = await connection.fetchval(
        f"EXPLAIN (FORMAT JSON) {statement.sql}", *statement.parameters
    )
    document = json.loads(plan) if isinstance(plan, str) else plan
    return float(document[0]["Plan"]["Total Cost"])


async def execute(
    statement: ResolvedQuery,
    *,
    guild_id: int,
    user_id: int,
    guild_role: Optional[str] = None,
    override_initiatives: Optional[tuple[int, ...]] = None,
) -> QueryResult:
    """Run an already-resolved statement as the asking user.

    The rows that come back are the rows that reader could reach through any
    other part of the app: the query role assumes the guild's schema and the
    initiative policies read the request's own identity, exactly as they do on
    every other path.
    """
    slot = _guild_slot(guild_id)
    try:
        await asyncio.wait_for(
            slot.acquire(), timeout=settings.QUERY_POOL_TIMEOUT_SECONDS
        )
    except (TimeoutError, asyncio.TimeoutError) as expired:
        raise QueryError(QueryMessages.BUSY, str(guild_id)) from expired

    try:
        async with AsyncSession(db_session.query_engine) as session:
            # Opened before anything else touches the connection. The bounds
            # below and the context after it are transaction-local, so they
            # need a transaction that is already open to be local *to*.
            await session.begin()
            sqlalchemy_connection = await session.connection()
            raw = await sqlalchemy_connection.get_raw_connection()
            connection = raw.driver_connection

            await _bound_transaction(sqlalchemy_connection)
            await set_rls_context(
                session,
                user_id=user_id,
                guild_id=guild_id,
                guild_role=guild_role,
                query=True,
                override_initiatives=override_initiatives,
            )

            cost = await _estimated_cost(connection, statement)
            if cost > settings.QUERY_MAX_COST:
                raise QueryError(QueryMessages.TOO_EXPENSIVE, f"{cost:.0f}")

            prepared = await connection.prepare(statement.sql)
            columns = tuple(attribute.name for attribute in prepared.get_attributes())

            limit = settings.QUERY_MAX_ROWS
            rows: list[dict[str, Any]] = []
            truncated = False
            async for record in prepared.cursor(*statement.parameters):
                if len(rows) == limit:
                    truncated = True
                    break
                rows.append(dict(record))

            await session.rollback()
            return QueryResult(
                columns=columns,
                rows=tuple(rows),
                cost=cost,
                truncated=truncated,
            )
    except QueryCanceledError as cancelled:
        raise QueryError(QueryMessages.TIMED_OUT) from cancelled
    finally:
        slot.release()


async def run(
    sql: str,
    *,
    guild_id: int,
    user_id: int,
    guild_role: Optional[str] = None,
    override_initiatives: Optional[tuple[int, ...]] = None,
) -> QueryResult:
    """Read *sql* and run what it resolves to."""
    return await execute(
        resolve(sql),
        guild_id=guild_id,
        user_id=user_id,
        guild_role=guild_role,
        override_initiatives=override_initiatives,
    )
