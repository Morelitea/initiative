"""Calendar-event source adapter: iCalendar (ics) and an importable JSON
envelope.

Events are a calendar, not per-entity artifacts, so BOTH formats emit one
combined file per request: ``ics`` is a single multi-event VCALENDAR (RRULE
and ATTENDEE/PARTSTAT preserved — the same serialization the old
``/calendar-events/export.ics`` endpoint produced), and ``json`` is one
``initiative-calendar-events`` envelope holding every event.

Selector: an explicit ``calendar_event_ids`` selection, or ``initiative_id``
(all exportable events in that initiative), or neither — every event visible
to the creator across the guild. Enumeration applies per-event sharing (the
DAC visible-ids subquery), so an export only ever contains events shared
with its creator.

Access rule: READ per event (exporting is a formatted read), enforced by the
``get_event_for_export`` / ``list_event_ids_for_export`` seams at both count
and build time, under the caller's RLS session.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.tenant.calendar_event import CalendarEvent
from app.services.export.adapters._common import selection_ids
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.i18n import localize_now


class CalendarEventAdapter:
    source = "calendar-event"
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
        # The enumerated path counts with ONE id query (the enumeration is
        # already DAC-filtered, so nothing needs a per-event fetch). An
        # explicit id selection keeps the per-event fetch+authorize — the
        # engine's contract is that count() rejects an unauthorized selection
        # BEFORE a job row exists, and the selection cap bounds it.
        if params.get("calendar_event_ids") or params.get("calendar_event_id"):
            return len(await self._events(session, user, guild_id, params))
        from app.services.tenant.calendar_events import list_event_ids_for_export

        return len(
            await list_event_ids_for_export(
                session,
                user,
                guild_id,
                initiative_id=_optional_int(params, "initiative_id"),
            )
        )

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        from app.services.tenant.ical_service import event_export_dict

        events = await self._events(session, user, guild_id, params)
        date = localize_now(datetime.now(timezone.utc), params.get("tz")).strftime(
            "%Y-%m-%d"
        )
        dicts = [event_export_dict(event) for event in events]
        stem = f"calendar-events-{date}"
        if format == "json":
            # The envelope is importable machine data — stays canonical, never
            # localized (translating field keys / enum values breaks import).
            data: dict[str, Any] = {
                "type": "initiative-calendar-events",
                "schema_version": 1,
                "events": dicts,
            }
            item = RenderItem(key=stem, data=data)
        else:  # ics
            item = RenderItem(
                key=stem,
                data={"layout": "ical", "events": dicts},
                filename=f"{stem}.ics",
            )
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=(item,),
        )

    async def _events(
        self, session: AsyncSession, user: User, guild_id: int, params: dict
    ) -> list[CalendarEvent]:
        from app.services.tenant.calendar_events import (
            get_event_for_export,
            list_event_ids_for_export,
        )

        if params.get("calendar_event_ids") or params.get("calendar_event_id"):
            event_ids = selection_ids(
                params,
                single_key="calendar_event_id",
                multi_key="calendar_event_ids",
            )
        else:
            initiative_id = _optional_int(params, "initiative_id")
            event_ids = await list_event_ids_for_export(
                session, user, guild_id, initiative_id=initiative_id
            )
        return [
            await get_event_for_export(session, user, guild_id, event_id=event_id)
            for event_id in event_ids
        ]


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
