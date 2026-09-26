"""Cross-guild tool lists — the My Tools page.

The page is the guild home's table with the guild boundary taken off: pick a
tool, see everything of that kind that reaches you, across every community you
belong to. What "reaches you" means, what the search box narrows and what the
made-by-me toggle does are stated once in
:mod:`app.services.tenant.my_tools`; this module is the request surface over
it.

``GET /me/{tool}`` is one route, mounted once for every tool out of
:data:`MY_TOOL_LISTS`. Projects, documents and calendars each had a cross-guild
list of their own before this page existed — for the task wizard, for My
Calendar — and each was its own copy of the same merge. They answer here now,
so the nine lists cannot drift. What survives per tool is the registry's
fields: what to eager-load, how a page of rows becomes the summaries its
response carries, the order a request that names none falls back to, and the
query parameters the route publishes. The response model is read from
:data:`TOOL_LISTS` — a tool answers in one shape whether it is asked inside a
guild or across them.

Every route keeps the path, method, name and parameters its tool already had,
so the published surface — its operation id included — is unchanged.

All nine run on ``UserSessionDep``: the caller is resolved against the shared
tables as their own platform role, and each guild is then entered with the
membership role they hold there (``cross_guild.gather_across_guilds``), which
is the same ``SET ROLE guild_<id>`` a ``/c/{guild_id}`` request makes.
"""

# NOT ``from __future__ import annotations``: the list handlers are built per
# tool from a signature assembled at import time, and the parameter annotations
# have to be real objects for FastAPI to read them.

import inspect
from dataclasses import dataclass
from typing import Annotated, Any, Awaitable, Callable, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import UserSessionDep, get_current_active_user
from app.api.v1.tenant_endpoints import documents as documents_endpoints
from app.api.v1.tenant_endpoints import projects as projects_endpoints
from app.api.v1.tenant_endpoints.tool_lists import (
    TOOL_LISTS,
    ListParam,
    page_param,
    page_size_param,
    search_param,
    sort_by_param,
    sort_dir_param,
)
from app.core.tools import Tool
from app.db.session import require_guild_context
from app.db.query import build_paginated_response, paginate_sequence
from app.models.platform.user import User
from app.schemas.tenant.calendar import CalendarSummary
from app.schemas.tenant.counter import CounterGroupSummary
from app.schemas.tenant.dashboard import DashboardSummary
from app.schemas.tenant.gallery import GallerySummary
from app.schemas.tenant.my_tools import MyToolCountsResponse
from app.schemas.tenant.post import PostRead
from app.schemas.tenant.queue import QueueSummary
from app.schemas.tenant.tool import ToolSummaryBase, serialize_tool
from app.schemas.tenant.wiki import WikiSummary
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.services.tenant import calendars as calendars_service
from app.services.tenant import counters as counters_service
from app.services.tenant import dashboards as dashboards_service
from app.services.tenant import documents as documents_service
from app.services.tenant import galleries as galleries_service
from app.services.tenant import my_tools as my_tools_service
from app.services.tenant import posts as posts_service
from app.services.tenant import queues as queues_service
from app.services.tenant import tags as tags_service
from app.services.tenant import wikis as wikis_service

me_router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------


_SORT_BY_DESCRIPTION = (
    "Order by one of: name, updated_at, created_at. Omit for this tool's own "
    "default order. There is no `initiative` here — a merged cross-guild list "
    "is ordered over the summaries themselves, which carry no initiative name."
)


def _params(tool: Tool, page_size: ListParam) -> tuple[ListParam, ...]:
    """The parameters a My Tools list publishes, in the order it publishes them.

    Only the page window differs between tools, so it is the argument.
    """
    plural = tool.plural.replace("_", " ")
    return (
        ListParam("guild_ids", Optional[List[int]], Query(default=None)),
        search_param(None),
        ListParam(
            "created_by_me",
            bool,
            Query(default=False, description=f"Narrow to {plural} the caller created."),
        ),
        sort_by_param(_SORT_BY_DESCRIPTION),
        sort_dir_param(),
        page_param(),
        page_size,
    )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MyToolList:
    """One tool's half of a cross-guild list.

    What to eager-load, how a page of rows becomes the summaries that tool's
    list response carries, the order it falls back to when the request asks for
    none, its page window, and its published description.
    """

    loader_options: Callable[[], list]
    #: async (session, rows, user) -> the response's ``items``. Runs inside the
    #: guild's routed session, so relationships resolve in its schema.
    serialize: Callable[[AsyncSession, list, User], Awaitable[list]]
    #: (row) -> the sort key used when the request names no order
    default_key: Callable[[Any], Any]
    #: The page window; the other parameters are every tool's.
    page_size: ListParam
    list_doc: str
    default_desc: bool = True
    #: (values) -> extra fields on the list response.
    response_extras: Optional[Callable[[dict], dict]] = None


def _summaries(
    schema: type[ToolSummaryBase],
) -> Callable[[AsyncSession, list, User], Awaitable[list]]:
    """The ordinary page: tag the rows, then turn each into its summary."""

    async def serialize(session: AsyncSession, rows: list, user: User) -> list:
        await tags_service.annotate_tags(session, rows)
        context = require_guild_context(session)
        return [
            serialize_tool(schema, row, context=context, user_id=user.id)
            for row in rows
        ]

    return serialize


async def _serialize_projects(session: AsyncSession, rows: list, user: User) -> list:
    # The projects list's own page serializer, which the guild-wide list runs
    # too: task summaries, tags, the reader's own order/favourites/views, and
    # the documents each project carries.
    return await projects_endpoints.serialize_project_page(
        session, user.id, rows, slim=False
    )


async def _serialize_documents(session: AsyncSession, rows: list, user: User) -> list:
    return await documents_endpoints.serialize_document_page(session, user.id, rows)


MY_TOOL_LISTS: dict[Tool, MyToolList] = {
    Tool.project: MyToolList(
        loader_options=projects_endpoints.project_load_options,
        serialize=_serialize_projects,
        default_key=lambda row: row.updated_at,
        page_size=page_size_param(20, ge=1, le=100),
        list_doc=(
            "List projects across all guilds the current user belongs to.\n"
            "\n"
            "Returns a paginated list filtered by DAC permissions, excluding\n"
            "archived and template projects. Supports optional guild, "
            "name-search and\n"
            "made-by-me filters."
        ),
    ),
    Tool.document: MyToolList(
        loader_options=documents_service.list_loader_options,
        serialize=_serialize_documents,
        default_key=lambda row: row.updated_at,
        # The one list that echoes the order it was asked for back to the
        # client, which its page reads to keep its column headers in step.
        response_extras=lambda values: {
            "sort_by": values.get("sort_by"),
            "sort_dir": values.get("sort_dir"),
        },
        page_size=page_size_param(20, ge=0, le=100),
        list_doc=(
            "Documents that reach the current user across every guild they "
            "belong to.\n"
            "\n"
            "An optional ``guild_ids`` filter narrows to a subset of guilds, "
            "and\n"
            "``created_by_me`` to the ones the caller wrote."
        ),
    ),
    Tool.queue: MyToolList(
        loader_options=queues_service.list_loader_options,
        serialize=_summaries(QueueSummary),
        default_key=lambda row: row.updated_at,
        page_size=page_size_param(20, ge=0, le=100),
        list_doc="Queues that reach the caller across every guild they belong to.",
    ),
    Tool.counter_group: MyToolList(
        loader_options=counters_service.list_loader_options,
        serialize=_summaries(CounterGroupSummary),
        default_key=lambda row: row.updated_at,
        page_size=page_size_param(20, ge=0, le=100),
        list_doc=(
            "Counter groups that reach the caller across every guild they belong to."
        ),
    ),
    Tool.calendar: MyToolList(
        loader_options=calendars_service.calendar_loader_options,
        serialize=_summaries(CalendarSummary),
        # By name, like the calendar list inside a guild: this one backs a
        # grouping panel, which is read down rather than scanned for what moved.
        default_key=lambda row: (row.name or "").lower(),
        default_desc=False,
        page_size=page_size_param(200, ge=1, le=200),
        list_doc=(
            "List the calendars visible to the user across all their guilds — "
            "the\n"
            "backing data for the My Calendar grouping panel and the My Tools "
            "table.\n"
            "\n"
            "Mirrors ``list_my_calendar_events``: visit each member guild "
            "schema under\n"
            "the user's own RLS context (guild isolation + DAC hold), merge, "
            "and\n"
            "paginate in Python (per-schema SQL can't limit across schemas). "
            "The WHERE\n"
            "legs are ``my_tools.scope_conditions`` — the same rules every "
            "cross-guild\n"
            "tool list reads; a guild calendar answers to no initiative switch "
            "and so\n"
            "belongs in this view like any other."
        ),
    ),
    Tool.dashboard: MyToolList(
        loader_options=dashboards_service.dashboard_loader_options,
        serialize=_summaries(DashboardSummary),
        default_key=lambda row: (row.name or "").lower(),
        default_desc=False,
        page_size=page_size_param(20, ge=0, le=100),
        list_doc="Dashboards that reach the caller across every guild they belong to.",
    ),
    Tool.post: MyToolList(
        loader_options=posts_service.list_loader_options,
        serialize=_summaries(PostRead),
        # The board's own date: when it went up, or when it is due to. A
        # scheduled draft — which only its writers see here — sorts by the day
        # it will land, not by the day somebody started it.
        default_key=lambda row: row.published_at or row.scheduled_for or row.created_at,
        page_size=page_size_param(20, ge=0, le=50),
        list_doc=(
            "Posts that reach the caller across every guild they belong to.\n"
            "\n"
            "Paged small like the board itself: these carry their bodies, and "
            "a body is\n"
            "an editor the client mounts."
        ),
    ),
    Tool.gallery: MyToolList(
        loader_options=galleries_service.list_loader_options,
        serialize=_summaries(GallerySummary),
        default_key=lambda row: row.updated_at,
        page_size=page_size_param(20, ge=0, le=100),
        list_doc=(
            "Galleries that reach the caller across every guild they belong "
            "to.\n"
            "\n"
            "Counts and covers are not carried here: a cross-guild list is "
            "merged in\n"
            "Python from one query per guild, and those annotations are "
            "per-guild\n"
            "grouped queries the merge has no session for. The card falls back "
            "to no\n"
            "picture, which is what a gallery looks like from outside its "
            "community."
        ),
    ),
    Tool.wiki: MyToolList(
        loader_options=wikis_service.list_loader_options,
        serialize=_summaries(WikiSummary),
        default_key=lambda row: row.updated_at,
        page_size=page_size_param(20, ge=0, le=100),
        list_doc=(
            "Wikis that reach the caller across every guild they belong to.\n"
            "\n"
            "The page count each row carries is the one this merge cannot "
            "fill: it is a\n"
            "grouped query per guild, and the merge holds no session for the "
            "guilds it\n"
            "did not read. A card then shows no count, which is what a wiki "
            "looks like\n"
            "from outside its community."
        ),
    ),
}


# ---------------------------------------------------------------------------
# The merge
# ---------------------------------------------------------------------------


async def list_across_guilds(
    session: AsyncSession,
    current_user: User,
    tool: Tool,
    *,
    guild_ids: Optional[List[int]],
    search: Optional[str],
    created_by_me: bool,
    sort_by: Optional[str],
    sort_dir: Optional[str],
    page: int,
    page_size: int,
) -> tuple[list, int]:
    """One page of ``tool`` across every guild the caller belongs to.

    Visits each guild's schema in turn and merges — per-schema ids collide, so
    a single statement can't span them. Ordering and slicing therefore happen
    over the merged list rather than in SQL.
    """
    spec = MY_TOOL_LISTS[tool]
    model = my_tools_service.tool_model(tool)
    target_guilds = await member_guild_ids(
        session, current_user.id, restrict_to=guild_ids
    )

    async def _fetch(guild_session: AsyncSession, guild_id: int) -> list:
        statement = (
            select(model)
            .where(
                *my_tools_service.scope_conditions(
                    tool,
                    user_id=current_user.id,
                    context=require_guild_context(guild_session),
                    search=search,
                    created_by_me=created_by_me,
                )
            )
            .options(*spec.loader_options())
        )
        rows = list((await guild_session.exec(statement)).unique().all())
        # Serialize inside the routed session: relationships resolve in this
        # guild's schema, and the next guild expunges these rows.
        return await spec.serialize(guild_session, rows, current_user)

    items = await gather_across_guilds(session, current_user.id, target_guilds, _fetch)
    items = my_tools_service.sort_merged(
        items,
        sort_by,
        sort_dir,
        default=spec.default_key,
        default_desc=spec.default_desc,
    )
    return paginate_sequence(items, page, page_size), len(items)


# ---------------------------------------------------------------------------
# Mounting
# ---------------------------------------------------------------------------


_CONTEXT_PARAMS: tuple[tuple[str, Any], ...] = (
    ("session", UserSessionDep),
    ("current_user", CurrentUserDep),
)


def _signature(params: tuple[ListParam, ...]) -> inspect.Signature:
    """The signature FastAPI reads off a tool's list handler.

    Keyword-only throughout, so the registry's declared order is what the
    published parameter list follows.
    """
    declared = [
        inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=annotation)
        for name, annotation in _CONTEXT_PARAMS
    ]
    declared += [
        inspect.Parameter(
            param.name,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=param.annotation,
            default=param.default,
        )
        for param in params
    ]
    return inspect.Signature(declared)


def _mount(tool: Tool, spec: MyToolList) -> None:
    """Mount ``GET /{tool}`` for one tool."""
    response_model = TOOL_LISTS[tool].response_model

    async def list_rows(session, current_user, **values):
        page, page_size = values["page"], values["page_size"]
        items, total_count = await list_across_guilds(
            session,
            current_user,
            tool,
            guild_ids=values["guild_ids"],
            search=values["search"],
            created_by_me=values["created_by_me"],
            sort_by=values["sort_by"],
            sort_dir=values["sort_dir"],
            page=page,
            page_size=page_size,
        )
        extras = spec.response_extras(values) if spec.response_extras else {}
        return response_model(
            **build_paginated_response(items, total_count, page, page_size, **extras)
        )

    list_rows.__signature__ = _signature(_params(tool, spec.page_size))
    me_router.add_api_route(
        f"/{tool.route_segment}",
        list_rows,
        methods=["GET"],
        response_model=response_model,
        name=f"list_my_{tool.plural}",
        description=spec.list_doc,
    )


@me_router.get("/tools/counts", response_model=MyToolCountsResponse)
async def get_my_tool_counts(
    session: UserSessionDep,
    current_user: CurrentUserDep,
    guild_ids: Optional[List[int]] = Query(default=None),
    created_by_me: bool = Query(
        default=False,
        description="Count only what the caller wrote, matching the list views.",
    ),
) -> MyToolCountsResponse:
    """How much of each tool reaches the caller, across their communities.

    The My Tools page's tabs: a tool with nothing behind it gets none, so the
    page never offers a table of nothing.
    """
    counts = await my_tools_service.count_across_guilds(
        session, current_user, guild_ids=guild_ids, created_by_me=created_by_me
    )
    return MyToolCountsResponse(counts={tool.value: n for tool, n in counts.items()})


for _tool, _spec in MY_TOOL_LISTS.items():
    _mount(_tool, _spec)
