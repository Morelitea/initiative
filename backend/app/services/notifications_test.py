"""Tests for the scheduled event-reminder dispatcher.

``process_event_reminders`` runs on a background poller using its own admin
session; these tests drive it directly and assert against committed rows
(the test harness commits real data and truncates between tests).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.calendar_event import CalendarEvent, CalendarEventAttendee, RSVPStatus
from app.models.event_reminder_dispatch import EventReminderDispatch
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.notifications import (
    _format_event_when,
    _run_event_reminder_pass,
    notify_initiative_membership,
)
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


@pytest.mark.unit
def test_format_event_when_localizes_to_recipient_timezone():
    """A timed event renders in the recipient's IANA timezone with its abbrev."""
    event = CalendarEvent(
        title="Sync",
        start_at=datetime(2026, 7, 1, 21, 30, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 1, 22, 30, tzinfo=timezone.utc),
        all_day=False,
    )
    la = User(timezone="America/Los_Angeles")
    assert _format_event_when(event, la) == "Wed, Jul 1, 2026 at 2:30 PM PDT"

    utc_user = User(timezone="UTC")
    assert _format_event_when(event, utc_user) == "Wed, Jul 1, 2026 at 9:30 PM UTC"


@pytest.mark.unit
def test_format_event_when_all_day_omits_time_and_zone():
    """All-day events show just the date, regardless of recipient timezone."""
    event = CalendarEvent(
        title="Holiday",
        start_at=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 1, 23, 59, tzinfo=timezone.utc),
        all_day=True,
    )
    assert _format_event_when(event, User(timezone="Asia/Tokyo")) == "Wed, Jul 1, 2026"


@pytest.mark.unit
def test_format_event_when_falls_back_on_bad_timezone():
    """An unrecognized timezone string falls back to UTC instead of raising."""
    event = CalendarEvent(
        title="Sync",
        start_at=datetime(2026, 7, 1, 21, 30, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 1, 22, 30, tzinfo=timezone.utc),
        all_day=False,
    )
    assert _format_event_when(event, User(timezone="Not/AZone")) == (
        "Wed, Jul 1, 2026 at 9:30 PM UTC"
    )


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


@pytest.mark.integration
async def test_notify_initiative_membership_carries_guild_context(session: AsyncSession):
    """The initiative_added notification must carry its guild so the merged
    cross-guild inbox can resolve/navigate it after schema-per-guild."""
    creator = await create_user(session, email="ini-creator@example.com")
    guild = await create_guild(session, creator=creator)
    initiative = await create_initiative(session, guild, creator, name="Onboarding")
    member = await create_user(session, email="ini-member@example.com")

    await notify_initiative_membership(
        session,
        member,
        initiative_id=initiative.id,
        initiative_name=initiative.name,
        guild_id=guild.id,
    )

    notifs = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == member.id,
                Notification.type == NotificationType.initiative_added,
            )
        )
    ).all()
    assert len(notifs) == 1
    data = notifs[0].data
    assert data["guild_id"] == guild.id
    assert data["target_path"] == f"/initiatives/{initiative.id}"
    assert f"guild_id={guild.id}" in data["smart_link"]
