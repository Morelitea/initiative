"""Calendar-events source adapter: "export events" is "list events, but render".

Queries through ``query_guild_calendar_events`` — the same scope, sharing and
property filters as the event list, executed under the caller's RLS session
(that query IS the authorization) — and renders every matching event into one
iCalendar file. Anyone who can see a calendar's events can export them, the
way anyone who can see a project's tasks can export those.

``params`` is the calendar page's own selector: ``{"initiative_id", "scope",
"calendar_ids", "property_filters"}``. It is what an ExportJob row persists,
and what the worker replays here at render time.
"""

from __future__ import annotations

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import require_guild_context
from app.models.platform.user import User
from app.models.tenant.calendar_event import CalendarEvent
from app.services.export.contract import RenderItem, RenderRequest
from app.services.tenant.ical_service import documents_for_events, event_export_dict


class CalendarEventsAdapter:
    source = "events"
    template_id = "data-table"
    formats = ("ics",)

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        _events, total = await _query(session, user, params, page=1)
        return total

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        events, _total = await _query(session, user, params, page=None)
        documents = await documents_for_events(session, events)
        dicts = [
            event_export_dict(event, documents.get(event.id, [])) for event in events
        ]
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=(RenderItem(key="events", data={"layout": "ical", "events": dicts}),),
        )


async def _query(
    session: AsyncSession, user: User, params: dict[str, Any], *, page: int | None
) -> tuple[list[CalendarEvent], int]:
    from app.api.v1.tenant_endpoints.calendar_events import (
        query_guild_calendar_events,
    )

    return await query_guild_calendar_events(
        session,
        user,
        require_guild_context(session),
        initiative_id=params.get("initiative_id"),
        guild_scope=params.get("scope") == "guild",
        calendar_ids=params.get("calendar_ids"),
        property_filters=params.get("property_filters"),
        page=page,
        page_size=1,
    )
