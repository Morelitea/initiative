"""Run a reader's own SQL against their guild's data.

Guild-scoped, and gated by nothing more than reaching it: the dependency that
admits the request decides who the reader is, and the query then runs under
exactly the context that dependency established — same identity, same guild,
same grant if there is one. A query therefore returns what its author reaches
through any other part of the app, which is why membership is the whole of the
permission question here.

What the statement may say, and what running it may cost, are answered in
:mod:`app.services.query`.
"""

from typing import Annotated, Iterable

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import GuildContext, RLSSessionDep, get_guild_membership
from app.core.messages import QueryMessages
from app.db.session import rls_context_params
from app.schemas.sql_query import (
    QueryColumnDescription,
    QueryRequest,
    QueryResponse,
    QueryShapeResponse,
)
from app.services import query as query_service

router = APIRouter()

#: What each refusal is, as HTTP. Everything not named here is something the
#: reader can fix in the statement.
_STATUS = {
    QueryMessages.BUSY: status.HTTP_429_TOO_MANY_REQUESTS,
    QueryMessages.TIMED_OUT: status.HTTP_504_GATEWAY_TIMEOUT,
}


@router.post("/query/describe", response_model=QueryShapeResponse)
async def describe_query(
    payload: QueryRequest,
    session: RLSSessionDep,
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> QueryShapeResponse:
    """Say what one statement would return, without running it.

    Costs a plan and no rows, so a builder may ask as often as it likes.
    """
    try:
        columns = await query_service.describe(
            payload.sql, context=rls_context_params(session)
        )
    except query_service.QueryError as refused:
        raise HTTPException(
            status_code=_STATUS.get(refused.code, status.HTTP_400_BAD_REQUEST),
            detail=refused.code,
        ) from refused
    return QueryShapeResponse(columns=_described(columns))


def _described(
    columns: Iterable[query_service.QueryColumn],
) -> list[QueryColumnDescription]:
    """The executor's columns on the wire. Both endpoints answer with them."""
    return [
        QueryColumnDescription(name=column.name, type=column.type) for column in columns
    ]


@router.post("/query", response_model=QueryResponse)
async def run_query(
    payload: QueryRequest,
    session: RLSSessionDep,
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> QueryResponse:
    """Read one statement and return its rows."""
    try:
        result = await query_service.run(
            payload.sql, context=rls_context_params(session)
        )
    except query_service.QueryError as refused:
        raise HTTPException(
            status_code=_STATUS.get(refused.code, status.HTTP_400_BAD_REQUEST),
            detail=refused.code,
        ) from refused
    return QueryResponse(
        columns=_described(result.columns),
        rows=[list(row) for row in result.rows],
        truncated=result.truncated,
    )
