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

from datetime import datetime, timezone
from typing import Any

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import CalendarEvent
from app.services.export.adapters._common import selection_ids
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.i18n import localize_now
from app.services.platform.csv_export import safe_filename_component


class CalendarAdapter:
    source = "calendar"
    # Required by the SourceAdapter protocol; neither format uses a template.
    template_id = "data-table"
    formats = frozenset({"ics", "json"})

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
        if params.get("calendar_ids") or params.get("calendar_id"):
            calendars = await self._calendars(session, user, guild_id, params)
            return sum(len(calendar.events) for calendar in calendars)
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

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        calendars = await self._calendars(session, user, guild_id, params)
        date = localize_now(datetime.now(timezone.utc), params.get("tz")).strftime(
            "%Y-%m-%d"
        )
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=tuple(
                build_calendar_item(calendar, format, date) for calendar in calendars
            ),
        )

    async def _calendars(
        self, session: AsyncSession, user: User, guild_id: int, params: dict
    ) -> list[Calendar]:
        from app.services.tenant.calendars import (
            get_calendar_for_export,
            list_calendar_ids_for_export,
        )

        if params.get("calendar_ids") or params.get("calendar_id"):
            calendar_ids = selection_ids(
                params,
                single_key="calendar_id",
                multi_key="calendar_ids",
            )
        else:
            initiative_id = _optional_int(params, "initiative_id")
            calendar_ids = await list_calendar_ids_for_export(
                session, user, guild_id, initiative_id=initiative_id
            )
        return [
            await get_calendar_for_export(
                session, user, guild_id, calendar_id=calendar_id
            )
            for calendar_id in calendar_ids
        ]


def build_calendar_item(calendar: Calendar, format: str, date: str) -> RenderItem:
    """One render item per calendar: an ``ics`` VCALENDAR or an importable
    ``initiative-calendar`` JSON envelope, both carrying every event."""
    from app.services.tenant.ical_service import event_export_dict

    dicts = [event_export_dict(event) for event in calendar.events]
    stem = safe_filename_component(calendar.name).lower()
    if format == "json":
        # The envelope is importable machine data — stays canonical, never
        # localized (translating field keys / enum values breaks import).
        return RenderItem(
            key=f"{stem}-{date}.initiative-calendar",
            data=_envelope(calendar, dicts),
        )
    return RenderItem(
        key=f"{stem}-{date}",
        data={"layout": "ical", "events": dicts},
        filename=f"{stem}-{date}.ics",
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
