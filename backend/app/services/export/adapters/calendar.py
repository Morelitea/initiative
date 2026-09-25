"""Calendar source adapter: iCalendar (ics) and an importable JSON envelope,
one file PER CALENDAR.

A calendar is the shareable container for its events, so each selected
calendar renders its own file: ``ics`` is a single multi-event VCALENDAR
(RRULE and ATTENDEE/PARTSTAT preserved), and ``json`` is one
``initiative-calendar`` envelope holding the calendar plus every event.

Selector: an explicit ``calendar_ids`` selection, or ``initiative_id`` (all
exportable calendars in that initiative), or neither — every calendar visible
to the creator across the guild. Enumeration applies per-calendar sharing (the
DAC visible-ids subquery), so an export only ever contains calendars shared
with its creator.

Access rule: READ per calendar (exporting is a formatted read), enforced by
the ``get_calendar_for_export`` / ``list_calendar_ids_for_export`` seams at
both count and build time, under the caller's RLS session.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.tenant.ical_service import documents_for_events
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import CalendarEvent
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
    export_stem,
)
from app.services.export.contract import RenderItem
from app.services.permissions import EXPORT_ACCESS


class CalendarAdapter(ToolExportAdapter):
    tool = Tool.calendar
    format_choices = ("ics", "json")

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        # The enumerated path counts events with ONE query (the enumeration is
        # already DAC-filtered, so nothing needs a per-calendar fetch). An
        # explicit id selection keeps the per-calendar fetch+authorize — the
        # engine's contract is that count() rejects an unauthorized selection
        # BEFORE a job row exists, and the selection cap bounds it.
        if _is_selection(params):
            return await super().count(
                session, user=user, guild_id=guild_id, params=params, format=format
            )
        from app.services.tenant.calendars import list_calendar_ids_for_export

        calendar_ids = await list_calendar_ids_for_export(
            session,
            user,
            guild_id,
            initiative_id=_optional_int(params, "initiative_id"),
        )
        if not calendar_ids:
            return 0
        return (
            await session.exec(
                select(func.count())
                .select_from(CalendarEvent)
                .where(CalendarEvent.calendar_id.in_(calendar_ids))
            )
        ).one()

    async def load(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> list[Calendar]:
        """An explicit selection, or every calendar the creator may export in
        one initiative (or across the guild). A selection naming one they may
        not export is refused; the enumeration leaves those out instead, the
        way it leaves out calendars they cannot read at all."""
        if _is_selection(params):
            return [
                await self.fetch(session, user, guild_id, calendar_id)
                for calendar_id in self.selection(params)
            ]
        from app.services.permissions import level_of
        from app.services.tenant.calendars import (
            get_calendar_for_export,
            list_calendar_ids_for_export,
        )

        calendars = [
            await get_calendar_for_export(
                session, user, guild_id, calendar_id=calendar_id, access="read"
            )
            for calendar_id in await list_calendar_ids_for_export(
                session,
                user,
                guild_id,
                initiative_id=_optional_int(params, "initiative_id"),
            )
        ]
        return [
            calendar for calendar in calendars if level_of(calendar) == EXPORT_ACCESS
        ]

    async def fetch(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        calendar_id: int,
        /,
        *,
        access: str = EXPORT_ACCESS,
    ) -> Calendar:
        from app.services.tenant.calendars import get_calendar_for_export

        return await get_calendar_for_export(
            session, user, guild_id, calendar_id=calendar_id, access=access
        )

    async def initiative_ids(
        self, session: AsyncSession, user: User, guild_id: int, initiative_id: int, /
    ) -> list[int]:
        """None where the initiative has calendars switched off: the
        enumeration applies the switch."""
        from app.services.tenant.calendars import list_calendar_ids_for_export

        return await list_calendar_ids_for_export(
            session, user, guild_id, initiative_id=initiative_id
        )

    def rows(self, calendar: Calendar, /) -> int:
        return len(calendar.events)

    async def prepare(
        self, session: AsyncSession, calendars: list[Calendar], /
    ) -> dict[int, list]:
        # Every event across every calendar, once: the builders below are
        # synchronous and hold no session.
        return await documents_for_events(
            session, [event for calendar in calendars for event in calendar.events]
        )

    def item(self, calendar: Calendar, ctx: BuildContext, /) -> RenderItem:
        return build_calendar_item(calendar, ctx.format, ctx.date, ctx.prepared)


def _is_selection(params: dict) -> bool:
    """Whether this request named the calendars it wants, rather than asking
    for everything the creator can reach."""
    return bool(params.get("calendar_ids") or params.get("calendar_id"))


def build_calendar_item(
    calendar: Calendar,
    format: str,
    date: str,
    documents: dict[int, list] | None = None,
) -> RenderItem:
    """One render item per calendar: an ``ics`` VCALENDAR or an importable
    ``initiative-calendar`` JSON envelope, both carrying every event."""
    from app.services.tenant.ical_service import event_export_dict

    by_event = documents or {}
    dicts = [
        event_export_dict(event, by_event.get(event.id, []))
        for event in calendar.events
    ]
    if format == "json":
        # The envelope is importable machine data — stays canonical, never
        # localized (translating field keys / enum values breaks import).
        return RenderItem(
            key=envelope_key(Tool.calendar, calendar.name, date),
            data=_envelope(calendar, dicts),
        )
    stem = export_stem(calendar.name, date)
    return RenderItem(
        key=stem,
        data={"layout": "ical", "events": dicts},
        filename=f"{stem}.ics",
    )


def _envelope(calendar: Calendar, event_dicts: list[dict]) -> dict[str, Any]:
    return {
        "type": "initiative-calendar",
        "schema_version": 1,
        "name": calendar.name,
        "description": calendar.description,
        "color": calendar.color,
        "events": event_dicts,
    }


def _optional_int(params: dict, key: str) -> int | None:
    """Job params round-trip through JSON — validate, don't trust."""
    value = params.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        from app.core.messages import ExportMessages
        from app.services.export.engine import ExportError

        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
