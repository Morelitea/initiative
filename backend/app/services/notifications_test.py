"""Tests for the scheduled event-reminder dispatcher.

``process_event_reminders`` runs on a background poller using its own admin
session; these tests drive it directly and assert against committed rows
(the test harness commits real data and truncates between tests).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.calendar_event import CalendarEventAttendee, RSVPStatus
from app.models.event_reminder_dispatch import EventReminderDispatch
from app.models.notification import Notification, NotificationType
from app.services.notifications import _run_event_reminder_pass
from app.testing import (
    create_calendar_event,
    create_guild,
    create_initiative,
    create_user,
)


async def _dispatch(session: AsyncSession) -> None:
    """Drive the reminder pass with the test session (the worker opens its
    own AdminSessionLocal pointed at the dev DB)."""
    await _run_event_reminder_pass(session, now=datetime.now(timezone.utc))


async def _events_initiative(session: AsyncSession, creator):
    guild = await create_guild(session)
    initiative = await create_initiative(session, guild, creator, name="Reminders")
    initiative.events_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    return guild, initiative


async def _add_attendee(session, event, user, *, rsvp=RSVPStatus.pending):
    attendee = CalendarEventAttendee(
        calendar_event_id=event.id,
        user_id=user.id,
        guild_id=event.guild_id,
        rsvp_status=rsvp,
    )
    session.add(attendee)
    await session.commit()


async def _reminders_for(session: AsyncSession, user_id: int) -> list[Notification]:
    result = await session.exec(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == NotificationType.event_reminder,
        )
    )
    return list(result.all())


@pytest.mark.integration
async def test_event_reminder_fires_once_within_lead_window(
    session: AsyncSession,
):
    creator = await create_user(session, email="organizer@example.com")
    attendee = await create_user(
        session, email="attendee@example.com", event_reminder_minutes_before=15
    )
    _, initiative = await _events_initiative(session, creator)
    # Starts in 10 min; with a 15-min lead the reminder is already due.
    start_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    event = await create_calendar_event(
        session, initiative, creator, title="Standup", start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, event, attendee)

    await _dispatch(session)
    assert len(await _reminders_for(session, attendee.id)) == 1

    # Dedup: a second pass must not create another reminder.
    await _dispatch(session)
    assert len(await _reminders_for(session, attendee.id)) == 1

    dispatches = await session.exec(
        select(EventReminderDispatch).where(EventReminderDispatch.user_id == attendee.id)
    )
    assert len(list(dispatches.all())) == 1


@pytest.mark.integration
async def test_event_reminder_skipped_when_lead_time_off(session: AsyncSession):
    creator = await create_user(session, email="organizer2@example.com")
    attendee = await create_user(session, email="attendee2@example.com")
    # Turn reminders off via an UPDATE (mirrors the API; an explicit None on
    # INSERT would fall back to the column's server_default).
    attendee.event_reminder_minutes_before = None
    session.add(attendee)
    await session.commit()
    _, initiative = await _events_initiative(session, creator)
    start_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    event = await create_calendar_event(
        session, initiative, creator, title="Sync", start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, event, attendee)

    await _dispatch(session)
    assert await _reminders_for(session, attendee.id) == []


@pytest.mark.integration
async def test_event_reminder_not_due_when_outside_lead_window(session: AsyncSession):
    creator = await create_user(session, email="organizer3@example.com")
    attendee = await create_user(
        session, email="attendee3@example.com", event_reminder_minutes_before=15
    )
    _, initiative = await _events_initiative(session, creator)
    # Starts in 2 hours; a 15-min lead means the reminder is not yet due.
    start_at = datetime.now(timezone.utc) + timedelta(hours=2)
    event = await create_calendar_event(
        session, initiative, creator, title="Later", start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, event, attendee)

    await _dispatch(session)
    assert await _reminders_for(session, attendee.id) == []


@pytest.mark.integration
async def test_event_reminder_at_time_of_event_fires_at_start(session: AsyncSession):
    creator = await create_user(session, email="organizer5@example.com")
    attendee = await create_user(
        session, email="attendee5@example.com", event_reminder_minutes_before=0
    )
    _, initiative = await _events_initiative(session, creator)
    # Just started (within the grace window); a 0-minute lead is due now.
    start_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    event = await create_calendar_event(
        session, initiative, creator, title="Now", start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, event, attendee)

    await _dispatch(session)
    assert len(await _reminders_for(session, attendee.id)) == 1


@pytest.mark.integration
async def test_event_reminder_skips_declined_attendees(session: AsyncSession):
    creator = await create_user(session, email="organizer4@example.com")
    attendee = await create_user(
        session, email="attendee4@example.com", event_reminder_minutes_before=15
    )
    _, initiative = await _events_initiative(session, creator)
    start_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    event = await create_calendar_event(
        session, initiative, creator, title="Optional", start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, event, attendee, rsvp=RSVPStatus.declined)

    await _dispatch(session)
    assert await _reminders_for(session, attendee.id) == []
