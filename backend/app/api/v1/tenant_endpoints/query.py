"""Run a reader's own SQL against their guild's data.

Guild-scoped, and gated by nothing more than reaching it: the dependency that
admits the request decides who the reader is, and the query then runs under
exactly the context that dependency established — same identity, same guild,
same grant if there is one. A query therefore returns what its author reaches
through any other part of the app, which is why membership is the whole of the
permission question here.

A statement names datasets rather than a scope, so a caller that belongs to
one initiative sends its id and the rows come back narrowed to it. That only
ever removes rows — the reader still reaches exactly what they reach elsewhere —
and it is what lets an initiative's dashboard ask a guild-scoped question.

What the statement may say, and what running it may cost, are answered in
:mod:`app.services.query`.
"""

from typing import Annotated, Iterable

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import GuildContext, RLSSessionDep, get_guild_membership
from app.core.messages import QueryMessages
from app.db.session import rls_context_params
from app.schemas.sql_query import (
    QueryBuildRequest,
    QueryBuildResponse,
    QueryColumnDescription,
    QueryRequest,
    QueryResponse,
    QueryShapeResponse,
)
from app.services import query as query_service
from app.services.query import build as query_builder

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
        columns, relations = await query_service.describe(
            payload.sql,
            context=rls_context_params(session),
            initiative_id=payload.initiative_id,
        )
    except query_service.QueryError as refused:
        raise HTTPException(
            status_code=_STATUS.get(refused.code, status.HTTP_400_BAD_REQUEST),
            detail=refused.code,
        ) from refused
    return QueryShapeResponse(columns=_described(columns), relations=list(relations))


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
            payload.sql,
            context=rls_context_params(session),
            initiative_id=payload.initiative_id,
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
        relations=list(result.relations),
    )


@router.post("/query/build", response_model=QueryBuildResponse)
async def build_query(
    payload: QueryBuildRequest,
    session: RLSSessionDep,
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> QueryBuildResponse:
    """Write the statement a builder described, and say what it would return.

    Two answers in one call because the builder needs both on every edit: the
    SQL to store, and the columns to offer its slot pickers. Describing costs a
    plan and no rows, so asking on each click is affordable.
    """
    try:
        sql = query_builder.build(_spec(payload))
        columns, relations = await query_service.describe(
            sql,
            context=rls_context_params(session),
            initiative_id=payload.initiative_id,
        )
    except query_service.QueryError as refused:
        raise HTTPException(
            status_code=_STATUS.get(refused.code, status.HTTP_400_BAD_REQUEST),
            detail=refused.code,
        ) from refused
    return QueryBuildResponse(
        sql=sql, columns=_described(columns), relations=list(relations)
    )


def _spec(payload: QueryBuildRequest) -> query_builder.QuerySpec:
    """The request as the builder's own vocabulary."""
    return query_builder.QuerySpec(
        dataset=payload.dataset,
        columns=tuple(
            query_builder.Column(
                field=column.field,
                aggregate=column.aggregate,
                bucket=column.bucket,
                alias=column.alias,
            )
            for column in payload.columns
        ),
        where=tuple(
            query_builder.Condition(
                field=condition.field, op=condition.op, value=condition.value
            )
            for condition in payload.where
        ),
        group_by=tuple(payload.group_by),
        order_by=query_builder.Sort(
            field=payload.order_by.field, descending=payload.order_by.descending
        )
        if payload.order_by
        else None,
        limit=payload.limit,
    )
