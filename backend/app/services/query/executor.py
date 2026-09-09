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
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Mapping

from asyncpg.exceptions import (
    DataError,
    QueryCanceledError,
    UndefinedFunctionError,
)
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import QueryMessages
from app.db import session as db_session
from app.db.session import set_rls_context
from app.services.fields.spec import FieldType
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


@dataclass(frozen=True)
class QueryColumn:
    """One output column, named and typed before anything runs."""

    name: str
    type: FieldType


#: What a Postgres type is, in the vocabulary the field registry already uses.
#: Only the distinctions a reader's tile turns on: whether a value counts,
#: whether it falls on a timeline, whether it is a yes or no.
_NUMBER_TYPES = frozenset(
    {"int2", "int4", "int8", "numeric", "float4", "float8", "money"}
)
_DATE_TYPES = frozenset(
    {"date", "time", "timetz", "timestamp", "timestamptz", "interval"}
)


async def _enum_types(connection: Any, oids: set[int]) -> set[int]:
    """Which of these types are a closed vocabulary the database defines.

    Asked of the catalog rather than read off the description: a prepared
    statement reports every type as scalar, so an enum column is
    indistinguishable there from the text it is stored beside.
    """
    if not oids:
        return set()
    rows = await connection.fetch(
        "SELECT oid FROM pg_type WHERE oid = ANY($1::oid[]) AND typtype = 'e'",
        list(oids),
    )
    return {row["oid"] for row in rows}


def _column_type(attribute: Any, enum_oids: set[int]) -> FieldType:
    """What the database says an output column holds.

    The answer for an output the registry cannot name — a count, a case, a date
    truncated to its month — since a field selected on its own is described by
    the registry that declares it (:attr:`ResolvedQuery.column_types`). Only the
    distinctions a tile turns on, in the same words the registry uses.
    """
    postgres_type = attribute.type
    if postgres_type.oid in enum_oids:
        return FieldType.enum
    name = postgres_type.name
    if name in _NUMBER_TYPES:
        return FieldType.number
    if name in _DATE_TYPES:
        return FieldType.date
    if name == "bool":
        return FieldType.boolean
    return FieldType.text


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


#: The statement limits, as one bound statement. ``set_config`` is the function
#: form of ``SET LOCAL`` and takes its value as a parameter, where ``SET`` takes
#: only a literal — so the settings arrive bound rather than written into SQL.
#: The last is a constant: one query is one backend's worth of the server's
#: attention.
_TRANSACTION_LIMITS = text(
    "SELECT set_config('statement_timeout', :statement_timeout, true),"
    " set_config('work_mem', :work_mem, true),"
    " set_config('max_parallel_workers_per_gather', '0', true)"
)


async def _bound_transaction(connection: Any) -> None:
    """Put the limits on the transaction, before anything of the reader's runs.

    Issued through SQLAlchemy rather than the driver underneath it, so they
    land inside the transaction it is managing — all four are local to one, and
    ``SET TRANSACTION READ ONLY`` has to be the first thing in it, ahead of the
    statement that sets the rest.
    """
    await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    await connection.execute(
        _TRANSACTION_LIMITS,
        {
            "statement_timeout": str(int(settings.QUERY_STATEMENT_TIMEOUT_MS)),
            "work_mem": settings.QUERY_WORK_MEM,
        },
    )


async def _estimated_cost(connection: Any, statement: ResolvedQuery) -> float:
    plan = await connection.fetchval(
        f"EXPLAIN (FORMAT JSON) {statement.sql}", *statement.parameters
    )
    document = json.loads(plan) if isinstance(plan, str) else plan
    return float(document[0]["Plan"]["Total Cost"])


@asynccontextmanager
async def _translated_failures() -> AsyncIterator[None]:
    """Turn what the database says into what this surface answers.

    The two things a statement this surface accepted can still do: run out of
    the time it is allowed, or fail on a value — a division by zero, a value
    that will not convert, a function called with types it does not take. Both
    are the reader's statement rather than the app's, so both are told back
    with a code and what the database said, and both reach the reader whether
    the statement was run or only described.
    """
    try:
        yield
    except QueryCanceledError as cancelled:
        raise QueryError(QueryMessages.TIMED_OUT) from cancelled
    except (DataError, UndefinedFunctionError) as failed:
        raise QueryError(QueryMessages.EXECUTION_FAILED, str(failed)) from failed


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
    async with _translated_failures():
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


async def run(sql: str, *, context: Mapping[str, Any]) -> QueryResult:
    """Read *sql* and run what it resolves to."""
    return await execute(resolve(sql), context=context)


async def describe(sql: str, *, context: Mapping[str, Any]) -> tuple[QueryColumn, ...]:
    """What *sql* would return, without returning it.

    The statement is prepared and its description read back. Preparing plans;
    it does not execute, so this costs a plan and no rows however much data the
    statement would have touched — which is what makes it usable at save time,
    on every keystroke of a builder if need be.

    It runs in the same transaction and role as the real thing, because a
    statement is only preparable against the schema its reader is routed to.
    """
    statement = resolve(sql)
    routed = dict(context)
    routed["query"] = True
    _routed_guild(context)

    async with _translated_failures():
        async with AsyncSession(db_session.query_engine) as session:
            await session.begin()
            sqlalchemy_connection = await session.connection()
            raw = await sqlalchemy_connection.get_raw_connection()
            connection = raw.driver_connection

            await _bound_transaction(sqlalchemy_connection)
            await set_rls_context(session, **routed)
            prepared = await connection.prepare(statement.sql)
            attributes = prepared.get_attributes()
            enum_oids = await _enum_types(
                connection, {attribute.type.oid for attribute in attributes}
            )
            declared = statement.column_types
            columns = tuple(
                QueryColumn(
                    name=attribute.name,
                    type=(
                        declared[position]
                        if position < len(declared) and declared[position] is not None
                        else _column_type(attribute, enum_oids)
                    ),
                )
                for position, attribute in enumerate(attributes)
            )
            await session.rollback()
            return columns
