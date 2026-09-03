"""Cross-guild tool lists — the My Tools page.

The page is the guild home's table with the guild boundary taken off: pick a
tool, see everything of that kind that reaches you, across every community you
belong to. What "reaches you" means, what the search box narrows and what the
made-by-me toggle does are stated once in
:mod:`app.services.tenant.my_tools`; this module is the request surface over
it.

Three of the six tools answer here. Projects, documents and calendars had a
cross-guild list before this page existed — for the task wizard, for My
Calendar — and those stay in their own modules; they read the same rules from
the same place, so the six lists agree without being in one file.
"""

from dataclasses import dataclass
from typing import Annotated, Any, Callable, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.deps import UserSessionDep, get_current_active_user
from app.core.tools import Tool
from app.db.query import page_has_next, paginate_sequence
from app.models.platform.user import User
from app.schemas.tenant.counter import (
    CounterGroupListResponse,
    serialize_counter_group_summary,
)
from app.schemas.tenant.dashboard import (
    DashboardListResponse,
    serialize_dashboard_summary,
)
from app.schemas.tenant.my_tools import MyToolCountsResponse
from app.schemas.tenant.queue import QueueListResponse, serialize_queue_summary
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.services.tenant import counters as counters_service
from app.services.tenant import dashboards as dashboards_service
from app.services.tenant import my_tools as my_tools_service
from app.services.tenant import queues as queues_service

me_router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]

_SORT_BY_DESCRIPTION = (
    "Order by one of: name, updated_at, created_at. Omit for this tool's own "
    "default order. There is no `initiative` here — a merged cross-guild list "
    "is ordered over the summaries themselves, which carry no initiative name."
)


@dataclass(frozen=True)
class MyToolList:
    """One tool's half of a cross-guild list: what to eager-load, how to turn a
    row into the summary that tool's list response carries, and the order it
    falls back to when the request asks for none."""

    loader_options: Callable[[], list]
    serialize: Callable[[Any, User], Any]
    default_key: Callable[[Any], Any]
    default_desc: bool = True


MY_TOOL_LISTS: dict[Tool, MyToolList] = {
    Tool.queue: MyToolList(
        loader_options=queues_service.list_loader_options,
        serialize=lambda row, user: serialize_queue_summary(
            row,
            my_permission_level=resource_access.my_permission_level(
                row, Tool.queue, user
            ),
        ),
        default_key=lambda row: row.updated_at,
    ),
    Tool.counter_group: MyToolList(
        loader_options=counters_service.list_loader_options,
        serialize=lambda row, user: serialize_counter_group_summary(
            row,
            my_permission_level=resource_access.my_permission_level(
                row, Tool.counter_group, user
            ),
        ),
        default_key=lambda row: row.updated_at,
    ),
    Tool.dashboard: MyToolList(
        loader_options=dashboards_service.dashboard_loader_options,
        serialize=lambda row, user: serialize_dashboard_summary(row, user_id=user.id),
        default_key=lambda row: (row.name or "").lower(),
        default_desc=False,
    ),
}


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
                    guild_id=guild_id,
                    search=search,
                    created_by_me=created_by_me,
                )
            )
            .options(*spec.loader_options())
        )
        rows = (await guild_session.exec(statement)).unique().all()
        # Serialize inside the routed session: relationships resolve in this
        # guild's schema, and the next guild expunges these rows.
        return [spec.serialize(row, current_user) for row in rows]

    items = await gather_across_guilds(session, current_user.id, target_guilds, _fetch)
    items = my_tools_service.sort_merged(
        items,
        sort_by,
        sort_dir,
        default=spec.default_key,
        default_desc=spec.default_desc,
    )
    return paginate_sequence(items, page, page_size), len(items)


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


@me_router.get("/queues", response_model=QueueListResponse)
async def list_my_queues(
    session: UserSessionDep,
    current_user: CurrentUserDep,
    guild_ids: Optional[List[int]] = Query(default=None),
    search: Optional[str] = Query(default=None),
    created_by_me: bool = Query(default=False),
    sort_by: Optional[str] = Query(default=None, description=_SORT_BY_DESCRIPTION),
    sort_dir: Optional[str] = Query(default=None, description="asc (default) or desc."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
) -> QueueListResponse:
    """Queues that reach the caller across every guild they belong to."""
    items, total_count = await list_across_guilds(
        session,
        current_user,
        Tool.queue,
        guild_ids=guild_ids,
        search=search,
        created_by_me=created_by_me,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )
    return QueueListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=page_has_next(page, page_size, total_count),
    )


@me_router.get("/counter-groups", response_model=CounterGroupListResponse)
async def list_my_counter_groups(
    session: UserSessionDep,
    current_user: CurrentUserDep,
    guild_ids: Optional[List[int]] = Query(default=None),
    search: Optional[str] = Query(default=None),
    created_by_me: bool = Query(default=False),
    sort_by: Optional[str] = Query(default=None, description=_SORT_BY_DESCRIPTION),
    sort_dir: Optional[str] = Query(default=None, description="asc (default) or desc."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
) -> CounterGroupListResponse:
    """Counter groups that reach the caller across every guild they belong to."""
    items, total_count = await list_across_guilds(
        session,
        current_user,
        Tool.counter_group,
        guild_ids=guild_ids,
        search=search,
        created_by_me=created_by_me,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )
    return CounterGroupListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=page_has_next(page, page_size, total_count),
    )


@me_router.get("/dashboards", response_model=DashboardListResponse)
async def list_my_dashboards(
    session: UserSessionDep,
    current_user: CurrentUserDep,
    guild_ids: Optional[List[int]] = Query(default=None),
    search: Optional[str] = Query(default=None),
    created_by_me: bool = Query(default=False),
    sort_by: Optional[str] = Query(default=None, description=_SORT_BY_DESCRIPTION),
    sort_dir: Optional[str] = Query(default=None, description="asc (default) or desc."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
) -> DashboardListResponse:
    """Dashboards that reach the caller across every guild they belong to."""
    items, total_count = await list_across_guilds(
        session,
        current_user,
        Tool.dashboard,
        guild_ids=guild_ids,
        search=search,
        created_by_me=created_by_me,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )
    return DashboardListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=page_has_next(page, page_size, total_count),
    )
