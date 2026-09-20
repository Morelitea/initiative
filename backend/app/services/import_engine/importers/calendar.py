"""``initiative-calendar`` importer: one envelope holds a whole calendar —
the calendar row (the shareable container) plus its events. The importer
becomes the calendar's owner; events apply in per-event savepoints (the ICS
import's partial-success pattern) so a malformed event fails alone, never the
batch.

Attendees resolve by handle against the target initiative's members; the
matched keep their RSVP, the unmatched are reported. Linked document titles
in the envelope are informational and dropped."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.calendar import DEFAULT_CALENDAR_COLOR, Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
    RSVPStatus,
)
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.property import CalendarEventPropertyValue
from app.schemas.tenant.import_envelopes import (
    CalendarEnvelope,
    EventEnvelopeItem,
)
from app.services.import_engine.common import (
    ensure_tag,
    load_initiative_member_handles,
    handle_key,
    parse_datetime,
    unique_name,
)
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.context import ImportContext
from app.services.import_engine.importers._base import (
    grant_ownership,
    parse_envelope,
    resolve_property_values,
)
from app.services.tenant import tags as tags_service


class CalendarImporter:
    envelope_type = "initiative-calendar"
    permission = PermissionKey.create_calendars

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(CalendarEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        envelope: CalendarEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        return len(envelope.events) + 1

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: CalendarEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        guild_id = target_initiative.guild_id
        member_handles = await load_initiative_member_handles(
            session, initiative_id=target_initiative.id
        )

        existing_names = {
            row
            for row in (
                await session.exec(
                    select(Calendar.name).where(
                        Calendar.initiative_id == target_initiative.id
                    )
                )
            ).all()
        }
        calendar = Calendar(
            name=unique_name(existing_names, env.name),
            description=env.description,
            color=env.color or DEFAULT_CALENDAR_COLOR,
            initiative_id=target_initiative.id,
            guild_id=guild_id,
            created_by=importer.id,
        )
        session.add(calendar)
        await session.flush()

        await grant_ownership(
            session,
            tool=Tool.calendar,
            entity_id=calendar.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        created = 0
        failed = 0
        tags_created = 0
        tags_matched = 0
        props_created = 0
        props_matched = 0
        attendees_matched = 0
        unmatched_handles: set[str] = set()
        warnings: list[str] = []

        for item in env.events:
            try:
                async with session.begin_nested():
                    counts = await self._apply_event(
                        session,
                        item=item,
                        calendar_id=calendar.id,
                        initiative_id=target_initiative.id,
                        guild_id=guild_id,
                        importer=importer,
                        member_handles=member_handles,
                        unmatched_handles=unmatched_handles,
                        context=context,
                    )
            except Exception:
                failed += 1
                warnings.append(f"event_failed:{item.title[:80]}")
                continue
            created += 1
            tags_created += counts["tags_created"]
            tags_matched += counts["tags_matched"]
            props_created += counts["props_created"]
            props_matched += counts["props_matched"]
            attendees_matched += counts["attendees_matched"]

        await session.flush()
        return EnvelopeImportResult(
            entity_id=calendar.id,
            entity_title=calendar.name,
            created={
                "calendars": 1,
                "events": created,
                "tags": tags_created,
                "properties": props_created,
            },
            matched={
                "tags": tags_matched,
                "properties": props_matched,
                "attendees": attendees_matched,
            },
            failed={"events": failed} if failed else {},
            unmatched_handles=sorted(unmatched_handles),
            warnings=warnings,
        )

    async def _apply_event(
        self,
        session: AsyncSession,
        *,
        item: EventEnvelopeItem,
        calendar_id: int,
        initiative_id: int,
        guild_id: int,
        importer: User,
        member_handles: dict[str, int],
        unmatched_handles: set[str],
        context: ImportContext | None = None,
    ) -> dict[str, int]:
        start_at = parse_datetime(item.start_at)
        end_at = parse_datetime(item.end_at)
        if start_at is None or end_at is None:
            raise ValueError("unparseable event times")
        event = CalendarEvent(
            calendar_id=calendar_id,
            guild_id=guild_id,
            title=item.title,
            description=item.description,
            location=item.location,
            start_at=start_at,
            end_at=end_at,
            all_day=item.all_day,
            recurrence=json.dumps(item.recurrence) if item.recurrence else None,
            created_by=importer.id,
            # When the event was written down, not when it happens. Absent
            # leaves the model default: the moment of the import.
            **_created_at(item),
        )
        session.add(event)
        await session.flush()

        # An event is something other entries point at — a sprint with its
        # tasks in it — so it joins the job's ref map like a task does. The
        # edges themselves are written by the deferred pass, because the
        # tasks naming this sprint are in a different envelope.
        if context is not None:
            context.links.register(
                item.external_ref, SearchEntityType.calendar_event, event.id
            )

        attendees_matched = 0
        seen_user_ids: set[int] = set()
        for attendee in item.attendees:
            if not attendee.handle:
                continue
            uid = member_handles.get(handle_key(attendee.handle))
            if uid is None:
                unmatched_handles.add(attendee.handle)
                continue
            if uid in seen_user_ids:
                continue
            seen_user_ids.add(uid)
            try:
                rsvp = RSVPStatus(attendee.rsvp)
            except ValueError:
                rsvp = RSVPStatus.pending
            session.add(
                CalendarEventAttendee(
                    calendar_event_id=event.id,
                    user_id=uid,
                    guild_id=guild_id,
                    rsvp_status=rsvp,
                )
            )
            attendees_matched += 1

        tags_created = 0
        tags_matched = 0
        for tag_name in item.tags:
            resolved = await ensure_tag(
                session, guild_id=guild_id, name=tag_name, color="#6b7280"
            )
            if resolved.created:
                tags_created += 1
            else:
                tags_matched += 1
            session.add(
                tags_service.tag_edge(
                    tags_service.TAG_LINKS["calendar_event"], event.id, resolved.id
                )
            )

        attached = await resolve_property_values(
            session,
            initiative_id=initiative_id,
            values=item.properties,
            member_handles=member_handles,
        )
        for prop_id, column_kwargs in attached.column_kwargs_by_id.items():
            session.add(
                CalendarEventPropertyValue(
                    event_id=event.id, property_id=prop_id, **column_kwargs
                )
            )

        return {
            "tags_created": tags_created,
            "tags_matched": tags_matched,
            "props_created": attached.created,
            "props_matched": attached.matched,
            "attendees_matched": attendees_matched,
        }


def _created_at(item: EventEnvelopeItem) -> dict[str, datetime]:
    """The event's own creation time, where the envelope carried a readable
    one. Returned as kwargs so an absent or unparseable stamp falls through
    to the model default rather than overwriting it."""
    parsed = parse_datetime(item.created_at)
    return {"created_at": parsed} if parsed is not None else {}
