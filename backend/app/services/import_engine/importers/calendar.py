"""``initiative-calendar`` importer: one envelope holds a whole calendar —
the calendar row (the shareable container) plus its events. The importer
becomes the calendar's owner; events apply in per-event savepoints (the ICS
import's partial-success pattern) so a malformed event fails alone, never the
batch.

Attendees resolve by email against the target initiative's members; the
matched keep their RSVP, the unmatched are reported. Linked document titles
in the envelope are informational and dropped."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.tenant.calendar import DEFAULT_CALENDAR_COLOR, Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
    CalendarEventTag,
    RSVPStatus,
)
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.property import CalendarEventPropertyValue
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.schemas.tenant.import_envelopes import (
    CalendarEnvelope,
    EventEnvelopeItem,
)
from app.services.import_engine.common import (
    ensure_tag,
    load_initiative_member_emails,
    parse_datetime,
    unique_name,
)
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.importers._base import (
    parse_envelope,
    resolve_property_values,
)


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
    ) -> EnvelopeImportResult:
        env: CalendarEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        guild_id = target_initiative.guild_id
        member_emails = await load_initiative_member_emails(
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

        session.add(
            ResourceGrant(
                resource_type="calendar",
                resource_id=calendar.id,
                user_id=importer.id,
                role_id=None,
                level=ResourceAccessLevel.owner,
                guild_id=guild_id,
                initiative_id=target_initiative.id,
            )
        )

        created = 0
        failed = 0
        tags_created = 0
        tags_matched = 0
        props_created = 0
        props_matched = 0
        attendees_matched = 0
        unmatched_emails: set[str] = set()
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
                        member_emails=member_emails,
                        unmatched_emails=unmatched_emails,
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
            unmatched_emails=sorted(unmatched_emails),
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
        member_emails: dict[str, int],
        unmatched_emails: set[str],
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
        )
        session.add(event)
        await session.flush()

        attendees_matched = 0
        seen_user_ids: set[int] = set()
        for attendee in item.attendees:
            if not attendee.email:
                continue
            uid = member_emails.get(attendee.email)
            if uid is None:
                unmatched_emails.add(attendee.email)
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
                CalendarEventTag(calendar_event_id=event.id, tag_id=resolved.id)
            )

        attached = await resolve_property_values(
            session,
            initiative_id=initiative_id,
            values=item.properties,
            member_emails=member_emails,
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
