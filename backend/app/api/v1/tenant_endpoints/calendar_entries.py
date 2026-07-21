"""Calendar-entries aggregate — events + task markers in one request.

The calendar surfaces (an initiative's Events page and the cross-guild My
Calendar) render events and task start/due markers together over one bounded date
window. Historically each fired two list requests (events + tasks) and merged
them client-side. These endpoints return the union in a single round trip.

This is a **union under the existing gates**, not a new authorization surface:
each leg delegates to the exact query path of ``list_calendar_events`` /
``list_tasks`` (guild) and ``list_my_calendar_events`` / ``list_my_tasks`` (me),
so RLS + per-resource DAC are identical. The client keeps the merge, so the
response reuses the existing ``CalendarEventSummary`` and ``TaskListRead`` shapes.
"""

from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    RLSSessionDep,
    UserSessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
from app.db.session import get_admin_session
from app.models.platform.user import User
from app.schemas.tenant.calendar_entry import CalendarEntriesResponse
from app.schemas.tenant.calendar_event import serialize_calendar_event_summary
from app.api.v1.tenant_endpoints import calendar_events as calendar_events_api
from app.api.v1.tenant_endpoints import tasks as tasks_api

router = APIRouter()
# Cross-guild "my calendar" aggregate. Mounted under /api/v1/me.
me_router = APIRouter()

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


@router.get("/", response_model=CalendarEntriesResponse)
async def list_calendar_entries(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    start_after: Optional[datetime] = Query(default=None),
    start_before: Optional[datetime] = Query(default=None),
    property_filters: Optional[str] = Query(default=None),
    conditions: Optional[str] = Query(
        default=None,
        description="Task filter conditions (same JSON shape as GET /tasks).",
    ),
    tz: Optional[str] = Query(default=None),
    include_events: bool = Query(default=True),
    include_tasks: bool = Query(default=True),
) -> CalendarEntriesResponse:
    """Events + task markers for one guild's calendar over a date window.

    Skip a leg with ``include_events=false`` / ``include_tasks=false`` (e.g. when
    the calendar has that type toggled off).
    """
    events_out = []
    if include_events:
        events, _total = await calendar_events_api.query_guild_calendar_events(
            session,
            current_user,
            guild_context,
            initiative_id=initiative_id,
            start_after=start_after,
            start_before=start_before,
            property_filters=property_filters,
        )
        events_out = [
            serialize_calendar_event_summary(e, user_id=current_user.id) for e in events
        ]

    tasks_out = []
    if include_tasks:
        tasks_out = await tasks_api.query_guild_tasks(
            session,
            current_user,
            guild_context,
            conditions=conditions,
            tz=tz,
            start_after=start_after,
            start_before=start_before,
        )

    return CalendarEntriesResponse(events=events_out, tasks=tasks_out)


@me_router.get("/calendar-entries", response_model=CalendarEntriesResponse)
async def list_my_calendar_entries(
    admin_session: AdminSessionDep,
    user_session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_ids: Optional[List[int]] = Query(default=None),
    start_after: Optional[datetime] = Query(default=None),
    start_before: Optional[datetime] = Query(default=None),
    conditions: Optional[str] = Query(
        default=None,
        description="Task filter conditions (same JSON shape as GET /me/tasks).",
    ),
    tz: Optional[str] = Query(default=None),
    include_events: bool = Query(default=True),
    include_tasks: bool = Query(default=True),
) -> CalendarEntriesResponse:
    """Cross-guild events + assigned-task markers for the My Calendar page.

    The two legs use different engines by design: events aggregate per guild
    schema via the admin session (``gather_across_guilds``), tasks run on the
    ``platform_<tier>`` user session — the same split as ``/me/calendar-events``
    and ``/me/tasks``.
    """
    events_out = []
    if include_events:
        events = await calendar_events_api.query_my_calendar_events(
            admin_session,
            current_user,
            guild_ids=guild_ids,
            start_after=start_after,
            start_before=start_before,
        )
        events_out = [
            serialize_calendar_event_summary(e, user_id=current_user.id) for e in events
        ]

    tasks_out = []
    if include_tasks:
        tasks_out = await tasks_api.query_my_tasks_list(
            user_session,
            current_user,
            conditions=conditions,
            tz=tz,
            start_after=start_after,
            start_before=start_before,
        )

    return CalendarEntriesResponse(events=events_out, tasks=tasks_out)
