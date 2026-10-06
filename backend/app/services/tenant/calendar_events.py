"""Calendar event service layer — business logic for CRUD and attachments.

Events hold no grants of their own: access derives from the parent calendar's
DAC (``resource_type='calendar'``), the way tasks inherit project access. The
loaders here eager-load the parent calendar with what the permission engine
needs.
"""

from sqlalchemy import delete as sa_delete
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
)
from app.core.tools import Tool
from app.services.tenant import named_people
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


async def get_event(
    session: AsyncSession,
    event_id: int,
    *,
    populate_existing: bool = False,
) -> CalendarEvent | None:
    """Fetch a calendar event with all relationships loaded."""
    stmt = (
        select(CalendarEvent)
        .where(CalendarEvent.id == event_id)
        .options(
            selectinload(CalendarEvent.attendees).selectinload(
                CalendarEventAttendee.user
            ),
            selectinload(CalendarEvent.calendar).selectinload(Calendar.grants),
            selectinload(CalendarEvent.calendar).selectinload(Calendar.initiative),
            selectinload(CalendarEvent.calendar).undefer(Calendar.actions),
        )
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    event = result.one_or_none()
    if event is not None:
        await tags_service.annotate_tags(session, [event])
        await properties_service.annotate_properties(session, [event])
    return event


# ---------------------------------------------------------------------------
# Attendee helpers
# ---------------------------------------------------------------------------


async def set_event_attendees(
    session: AsyncSession,
    event: CalendarEvent,
    user_ids: list[int],
    *,
    calendar: Calendar,
    carried: bool = False,
) -> None:
    """Make ``user_ids`` the event's attendees.

    Everyone named must be able to open ``calendar``; ``carried`` is the
    existing list following the event somewhere new, which keeps those who
    still can rather than refusing. Someone already attending keeps their
    answer.
    """
    wanted = list(dict.fromkeys(user_ids))
    governing = named_people.Governing.of(Tool.calendar, calendar)
    if carried:
        keep = await named_people.readers(session, governing, wanted)
        wanted = [user_id for user_id in wanted if user_id in keep]
    else:
        await named_people.require_readers(session, governing, wanted)

    await session.exec(
        sa_delete(CalendarEventAttendee).where(
            CalendarEventAttendee.calendar_event_id == event.id,
            CalendarEventAttendee.user_id.not_in(wanted),
        )
    )
    present = set(
        (
            await session.exec(
                select(CalendarEventAttendee.user_id).where(
                    CalendarEventAttendee.calendar_event_id == event.id
                )
            )
        ).all()
    )
    session.add_all(
        CalendarEventAttendee(calendar_event_id=event.id, user_id=user_id)
        for user_id in wanted
        if user_id not in present
    )
