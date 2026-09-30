"""One occurrence of a repeating event, changed on its own.

An override is an ordinary event row in its series' calendar, naming the series
(``series_id``) and the start it has there (``original_start``). It is made the
first time an occurrence changes alone, from the series as it stands: its
fields, attendees and their answers, tags and properties. What it changed is
listed in ``overridden_fields``; everything else follows the series, so a
change to the series is written to its overrides too (``follow``).

Skipped and extra starts are the series' ``EXDATE`` and ``RDATE`` lines. A
split ("this and following") ends the series before an occurrence and starts a
new one there, and the overrides from that occurrence on move with it.

An attendee's answer for one occurrence is on its override's attendee row when
it has one, and otherwise in ``calendar_event_answers``: answering takes read
access, and making an override takes write.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import recurrence
from app.core.messages import CalendarEventMessages
from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAnswer,
    CalendarEventAttendee,
    RSVPStatus,
)
from app.models.tenant.property import CalendarEventPropertyValue
from app.services.tenant import calendar_events as events_service
from app.services.tenant import tags as tags_service

#: What an occurrence can change alone, as ``overridden_fields`` names it.
SCALARS = ("title", "description", "location")
TIMES = ("start_at", "end_at", "all_day")
LISTS = ("attendees", "tags", "properties")

_TAGS = tags_service.EXTRA_TAG_LINKS["calendar_event"]


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def mark(override: CalendarEvent, fields: Iterable[str]) -> None:
    """Record that the override changed ``fields`` (a time is all three)."""
    changed = set(override.overridden_fields) | set(fields)
    if changed & set(TIMES):
        changed |= set(TIMES)
    override.overridden_fields = sorted(changed)


def unmark(override: CalendarEvent, fields: Iterable[str]) -> None:
    """Let the override follow its series in ``fields`` again."""
    dropped = set(fields)
    if dropped & set(TIMES):
        dropped |= set(TIMES)
    override.overridden_fields = sorted(set(override.overridden_fields) - dropped)


async def overrides(
    session: AsyncSession, series: CalendarEvent
) -> list[CalendarEvent]:
    """The series' live overrides."""
    return list(
        (
            await session.exec(
                select(CalendarEvent).where(CalendarEvent.series_id == series.id)
            )
        ).all()
    )


async def changed_starts(
    session: AsyncSession, series_ids: Iterable[int]
) -> dict[int, set[datetime]]:
    """Each series' occurrences that have a row of their own, by start: the
    series leaves those out and the row stands in."""
    ids = sorted(set(series_ids))
    if not ids:
        return {}
    found: dict[int, set[datetime]] = {}
    rows = await session.exec(
        select(CalendarEvent.series_id, CalendarEvent.original_start).where(
            CalendarEvent.series_id.in_(ids)
        )
    )
    for series_id, start in rows.all():
        if series_id is not None and start is not None:
            found.setdefault(series_id, set()).add(_utc(start))
    return found


def require_occurrence(series: CalendarEvent, at: datetime | None) -> datetime:
    """``at`` as one of the series' starts, or 422."""
    if at is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=CalendarEventMessages.OCCURRENCE_REQUIRED,
        )
    at = _utc(at)
    if not series.recurrence or not recurrence.occurs(
        series.recurrence, series.start_at, series.recurrence_shift, at
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=CalendarEventMessages.NOT_AN_OCCURRENCE,
        )
    return at


async def _copy_lists(
    session: AsyncSession,
    source: CalendarEvent,
    target: CalendarEvent,
    lists: Iterable[str] = LISTS,
) -> None:
    """Give ``target`` the source's attendees (with their answers), tags or
    property values, replacing its own."""
    lists = set(lists)
    if "attendees" in lists:
        answers = {a.user_id: a.rsvp_status for a in source.attendees}
        await events_service.set_event_attendees(
            session,
            target,
            list(answers),
            calendar=source.calendar,
            carried=True,
        )
        await session.flush()
        for attendee in (
            await session.exec(
                select(CalendarEventAttendee).where(
                    CalendarEventAttendee.calendar_event_id == target.id
                )
            )
        ).all():
            if attendee.rsvp_status == RSVPStatus.pending:
                attendee.rsvp_status = answers.get(
                    attendee.user_id, attendee.rsvp_status
                )
                session.add(attendee)
    if "tags" in lists:
        await tags_service.replace_entity_tags(session, _TAGS, target.id, [])
        await tags_service.copy_entity_tags(session, _TAGS, {source.id: target.id})
    if "properties" in lists:
        await session.exec(
            sa_delete(CalendarEventPropertyValue).where(
                CalendarEventPropertyValue.event_id == target.id
            )
        )
        session.add_all(
            CalendarEventPropertyValue(
                **value.model_dump(
                    exclude={"id", "event_id", "created_at", "updated_at"}
                ),
                event_id=target.id,
            )
            for value in source.property_values
        )
    await session.flush()


async def occurrence(
    session: AsyncSession, series: CalendarEvent, at: datetime
) -> CalendarEvent:
    """The override for the series' occurrence at ``at``, made from the series
    the first time it is asked for. Answers kept for that occurrence move onto
    its attendee rows."""
    at = require_occurrence(series, at)
    existing = (
        await session.exec(
            select_including_deleted(CalendarEvent).where(
                CalendarEvent.series_id == series.id,
                CalendarEvent.original_start == at,
            )
        )
    ).one_or_none()
    if existing is not None:
        if existing.deleted_at is not None:
            from app.services.tenant.soft_delete import restore_entity

            await restore_entity(session, existing)
        return existing

    override = CalendarEvent(
        calendar_id=series.calendar_id,
        title=series.title,
        description=series.description,
        location=series.location,
        start_at=at,
        end_at=at + (series.end_at - series.start_at),
        all_day=series.all_day,
        series_id=series.id,
        original_start=at,
        created_by=series.created_by,
    )
    session.add(override)
    await session.flush()
    await _copy_lists(session, series, override)
    answers = (
        await session.exec(
            select(CalendarEventAnswer).where(
                CalendarEventAnswer.calendar_event_id == series.id,
                CalendarEventAnswer.original_start == at,
            )
        )
    ).all()
    for answer in answers:
        await answer_on(session, override, answer.user_id, answer.rsvp_status)
        await session.delete(answer)
    await session.flush()
    return override


async def answer_on(
    session: AsyncSession, event: CalendarEvent, user_id: int, answer: RSVPStatus
) -> None:
    """``user_id``'s answer on the event's own attendee row."""
    row = (
        await session.exec(
            select(CalendarEventAttendee).where(
                CalendarEventAttendee.calendar_event_id == event.id,
                CalendarEventAttendee.user_id == user_id,
            )
        )
    ).one_or_none() or CalendarEventAttendee(
        calendar_event_id=event.id, user_id=user_id
    )
    row.rsvp_status = answer
    session.add(row)


async def answer_occurrence(
    session: AsyncSession,
    series: CalendarEvent,
    at: datetime,
    user_id: int,
    answer: RSVPStatus,
) -> None:
    """``user_id``'s answer for one occurrence: on its override when it has
    one, else kept beside the series."""
    at = require_occurrence(series, at)
    override = (
        await session.exec(
            select(CalendarEvent).where(
                CalendarEvent.series_id == series.id,
                CalendarEvent.original_start == at,
            )
        )
    ).one_or_none()
    if override is not None:
        await answer_on(session, override, user_id, answer)
        return
    row = await session.get(CalendarEventAnswer, (series.id, user_id, at))
    if row is None:
        row = CalendarEventAnswer(
            calendar_event_id=series.id,
            user_id=user_id,
            original_start=at,
            rsvp_status=answer,
        )
    row.rsvp_status = answer
    session.add(row)


async def answer_series(
    session: AsyncSession, series: CalendarEvent, user_id: int, answer: RSVPStatus
) -> None:
    """``user_id``'s answer for the whole series: the series' own, and each
    override's where it still said what the series did."""
    before = next(
        (a.rsvp_status for a in series.attendees if a.user_id == user_id), None
    )
    await answer_on(session, series, user_id, answer)
    for override in await overrides(session, series):
        row = (
            await session.exec(
                select(CalendarEventAttendee).where(
                    CalendarEventAttendee.calendar_event_id == override.id,
                    CalendarEventAttendee.user_id == user_id,
                )
            )
        ).one_or_none()
        if row is not None and row.rsvp_status == (before or RSVPStatus.pending):
            row.rsvp_status = answer
            session.add(row)
    await session.exec(
        sa_delete(CalendarEventAnswer).where(
            CalendarEventAnswer.calendar_event_id == series.id,
            CalendarEventAnswer.user_id == user_id,
            CalendarEventAnswer.rsvp_status == (before or RSVPStatus.pending),
        )
    )


async def answers_for(
    session: AsyncSession, series_id: int, at: datetime
) -> dict[int, RSVPStatus]:
    """The answers kept for one occurrence without a row of its own."""
    rows = await session.exec(
        select(CalendarEventAnswer).where(
            CalendarEventAnswer.calendar_event_id == series_id,
            CalendarEventAnswer.original_start == _utc(at),
        )
    )
    return {row.user_id: row.rsvp_status for row in rows.all()}


async def follow(
    session: AsyncSession, series: CalendarEvent, fields: Iterable[str]
) -> None:
    """Write the series' ``fields`` to its overrides that didn't change them."""
    fields = set(fields)
    if not fields:
        return
    length = series.end_at - series.start_at
    for override in await overrides(session, series):
        free = fields - set(override.overridden_fields)
        for name in free & set(SCALARS):
            setattr(override, name, getattr(series, name))
        if free & set(TIMES):
            override.start_at = override.original_start or override.start_at
            override.end_at = override.start_at + length
            override.all_day = series.all_day
        override.calendar_id = series.calendar_id
        session.add(override)
        if lists := free & set(LISTS):
            await _copy_lists(session, series, override, lists)


async def rehome(
    session: AsyncSession,
    series: CalendarEvent,
    *,
    old_shift: int,
    moved: bool,
    deleted_by: int | None,
) -> int:
    """Overrides of a series whose start or rule changed: on the same picked
    day at the new time when the start moved, and binned where the series no
    longer has that occurrence. Returns how many were binned."""
    from app.services.tenant.soft_delete import trash

    binned = 0
    length = series.end_at - series.start_at
    for override in await overrides(session, series):
        start = override.original_start
        if start is None:
            continue
        if moved:
            start = recurrence.rehomed(
                start, old_shift, series.recurrence_shift, series.start_at
            )
        if not series.recurrence or not recurrence.occurs(
            series.recurrence, series.start_at, series.recurrence_shift, start
        ):
            await trash(session, override, deleted_by_user_id=deleted_by)
            binned += 1
            continue
        override.original_start = start
        if not set(TIMES) & set(override.overridden_fields):
            override.start_at, override.end_at = start, start + length
        session.add(override)
    # Answers kept for an occurrence go where it went, or with it.
    for answer in (
        await session.exec(
            select(CalendarEventAnswer).where(
                CalendarEventAnswer.calendar_event_id == series.id
            )
        )
    ).all():
        start = (
            recurrence.rehomed(
                answer.original_start,
                old_shift,
                series.recurrence_shift,
                series.start_at,
            )
            if moved
            else answer.original_start
        )
        still = series.recurrence and recurrence.occurs(
            series.recurrence, series.start_at, series.recurrence_shift, start
        )
        await session.delete(answer)
        if still:
            await session.flush()
            session.add(
                CalendarEventAnswer(
                    calendar_event_id=series.id,
                    user_id=answer.user_id,
                    original_start=start,
                    rsvp_status=answer.rsvp_status,
                )
            )
    return binned


async def split(
    session: AsyncSession, series: CalendarEvent, at: datetime
) -> CalendarEvent:
    """End the series before its occurrence ``at`` and start a new one there
    with the rest of it: its fields, attendees, tags and properties, and the
    overrides and answers from ``at`` on. The first part keeps its row, and so
    its links."""
    at = require_occurrence(series, at)
    head, tail = recurrence.split(
        series.recurrence or "", series.start_at, series.recurrence_shift, at
    )
    if head is None:
        return series
    rest = CalendarEvent(
        calendar_id=series.calendar_id,
        title=series.title,
        description=series.description,
        location=series.location,
        start_at=at,
        end_at=at + (series.end_at - series.start_at),
        all_day=series.all_day,
        recurrence=tail,
        recurrence_shift=series.recurrence_shift,
        created_by=series.created_by,
    )
    session.add(rest)
    await session.flush()
    await _copy_lists(session, series, rest)
    for override in await overrides(session, series):
        if override.original_start is not None and _utc(override.original_start) >= at:
            override.series_id = rest.id
            session.add(override)
    for answer in (
        await session.exec(
            select(CalendarEventAnswer).where(
                CalendarEventAnswer.calendar_event_id == series.id,
                CalendarEventAnswer.original_start >= at,
            )
        )
    ).all():
        session.add(
            CalendarEventAnswer(
                calendar_event_id=rest.id,
                user_id=answer.user_id,
                original_start=answer.original_start,
                rsvp_status=answer.rsvp_status,
            )
        )
        await session.delete(answer)
    series.recurrence = head
    session.add(series)
    await session.flush()
    return rest


async def end_before(
    session: AsyncSession,
    series: CalendarEvent,
    at: datetime,
    *,
    deleted_by: int | None,
) -> bool:
    """Stop the series before its occurrence ``at``, binning the overrides
    from there on. False when ``at`` is its first, so nothing is left."""
    from app.services.tenant.soft_delete import trash

    at = require_occurrence(series, at)
    head, _tail = recurrence.split(
        series.recurrence or "", series.start_at, series.recurrence_shift, at
    )
    if head is None:
        return False
    for override in await overrides(session, series):
        if override.original_start is not None and _utc(override.original_start) >= at:
            await trash(session, override, deleted_by_user_id=deleted_by)
    await session.exec(
        sa_delete(CalendarEventAnswer).where(
            CalendarEventAnswer.calendar_event_id == series.id,
            CalendarEventAnswer.original_start >= at,
        )
    )
    series.recurrence = head
    session.add(series)
    return True


async def skip(
    session: AsyncSession,
    series: CalendarEvent,
    at: datetime,
    *,
    deleted_by: int | None,
) -> None:
    """Skip the series' occurrence at ``at``, binning its override."""
    from app.services.tenant.soft_delete import trash

    at = require_occurrence(series, at)
    for override in await overrides(session, series):
        if override.original_start is not None and _utc(override.original_start) == at:
            await trash(session, override, deleted_by_user_id=deleted_by)
    await session.exec(
        sa_delete(CalendarEventAnswer).where(
            CalendarEventAnswer.calendar_event_id == series.id,
            CalendarEventAnswer.original_start == at,
        )
    )
    series.recurrence = recurrence.skipped(
        series.recurrence or "", series.recurrence_shift, at
    )
    session.add(series)


async def detach(
    session: AsyncSession, series: CalendarEvent, at: datetime
) -> CalendarEvent:
    """Copy the occurrence at ``at`` out into an event of its own, which the
    series then skips."""
    event = await occurrence(session, series, at)
    event.series_id = None
    event.original_start = None
    event.overridden_fields = []
    session.add(event)
    series.recurrence = recurrence.skipped(
        series.recurrence or "", series.recurrence_shift, _utc(at)
    )
    session.add(series)
    await session.flush()
    return event
