"""Run a resolved query, inside everything that bounds it.

A statement arrives here already read, validated and rewritten
(:mod:`app.services.query.resolve`). What happens here is the running of it:
under which role, in which transaction, against which limits.

Five things bound a query, and they are independent of each other:

* a **pool of its own**, so these statements wait for each other rather than
  for the requests serving every other page;
* a **cap per guild** on how many run at once, held in the database so it is
  the whole deployment's cap rather than each process's;
* a **read-only transaction**, which refuses a write whatever the statement
  says;
* the **query role**, which holds ``SELECT`` and no more;
* **statement limits** — a time bound, a memory bound, no parallel workers —
  and a **planner estimate** checked before anything runs.

The last one is the only one that can refuse a statement that is otherwise
perfectly legal, and it does so without executing it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from asyncpg.exceptions import (
    DataError,
    QueryCanceledError,
    UndefinedFunctionError,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import QueryMessages
from app.db import session as db_session
from app.db.session import set_rls_context
from app.services.query.resolve import QueryError, ResolvedQuery, resolve


@dataclass(frozen=True)
class QueryResult:
    """What a query returned, and what it cost to say so."""

    #: Output names, in order. Not necessarily distinct — ``SELECT t.id, p.id``
    #: is a legal query and names both columns ``id``.
    columns: tuple[str, ...]
    #: One tuple per row, positional against :attr:`columns`. Positional rather
    #: than keyed for the reason above: a mapping keeps one value per name.
    rows: tuple[tuple[Any, ...], ...]
    #: The planner's estimate for the statement that ran.
    cost: float
    #: Whether there were more rows than one query returns.
    truncated: bool


#: Names the query surface's locks apart from anything else that takes one.
#: Advisory locks are keyed by two integers and share one space per database.
_LOCK_SPACE = 0x51_55_45_52  # "QUER"


async def _claim_a_slot(connection: Any, guild_id: int) -> bool:
    """Take one of this guild's slots, or report that it has none free.

    The slots are advisory locks rather than a counter in this process, so the
    cap is the deployment's however many workers or replicas serve it. Each is
    held for the transaction and released when it ends, so a query that fails
    or is cancelled gives its slot back without anything having to notice.
    """
    for slot in range(settings.QUERY_MAX_CONCURRENT_PER_GUILD):
        taken = await connection.fetchval(
            "SELECT pg_try_advisory_xact_lock($1, $2)",
            _LOCK_SPACE + int(guild_id),
            slot,
        )
        if taken:
            return True
    return False


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


def _routed_guild(context: Mapping[str, Any]) -> int:
    """Which guild this context reads. A grantee routes by the grant."""
    guild_id = context.get("guild_id") or context.get("pam_guild_id")
    if guild_id is None:
        raise QueryError(QueryMessages.MISSING_RELATION)
    return int(guild_id)


async def execute(
    statement: ResolvedQuery,
    *,
    context: Mapping[str, Any],
) -> QueryResult:
    """Run an already-resolved statement under *context*.

    *context* is what the request's own session established
    (:func:`app.db.session.rls_context_params`), replayed here with the query
    role selected. The rows that come back are therefore the rows that reader
    reaches through any other part of the app — a member's, a read-only
    member's, a grantee's — decided once, by the dependency that admitted the
    request, rather than again here.
    """
    guild_id = _routed_guild(context)
    routed = dict(context)
    routed["query"] = True
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
            if not await _claim_a_slot(connection, guild_id):
                raise QueryError(QueryMessages.BUSY, str(guild_id))
            await set_rls_context(session, **routed)

            cost = await _estimated_cost(connection, statement)
            if cost > settings.QUERY_MAX_COST:
                raise QueryError(QueryMessages.TOO_EXPENSIVE, f"{cost:.0f}")

            prepared = await connection.prepare(statement.sql)
            columns = tuple(attribute.name for attribute in prepared.get_attributes())

            limit = settings.QUERY_MAX_ROWS
            rows: list[tuple[Any, ...]] = []
            truncated = False
            async for record in prepared.cursor(*statement.parameters):
                if len(rows) >= limit:
                    truncated = True
                    break
                rows.append(tuple(record))

            await session.rollback()
            return QueryResult(
                columns=columns,
                rows=tuple(rows),
                cost=cost,
                truncated=truncated,
            )
    except QueryCanceledError as cancelled:
        raise QueryError(QueryMessages.TIMED_OUT) from cancelled
    except (DataError, UndefinedFunctionError) as failed:
        # The database's answer to a statement it accepted and could not
        # finish: a division by zero, a value that will not convert, a
        # function called with types it does not take. The reader wrote the
        # statement, so they are told what the database said about it.
        raise QueryError(QueryMessages.EXECUTION_FAILED, str(failed)) from failed


async def run(sql: str, *, context: Mapping[str, Any]) -> QueryResult:
    """Read *sql* and run what it resolves to."""
    return await execute(resolve(sql), context=context)
