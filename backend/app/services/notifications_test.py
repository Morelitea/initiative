"""Tests for the scheduled event-reminder dispatcher.

``process_event_reminders`` runs on a background poller using its own admin
session; these tests drive it directly and assert against committed rows
(the test harness commits real data and truncates between tests).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.models.calendar_event import CalendarEvent, CalendarEventAttendee, RSVPStatus
from app.models.event_reminder_dispatch import EventReminderDispatch
from app.models.notification import Notification, NotificationType
from app.models.task import (
    Task,
    TaskAssignee,
    TaskPriority,
    TaskStatus,
    TaskStatusCategory,
)
from app.models.task_assignment_digest import TaskAssignmentDigestItem
from app.models.user import User
from app.services import email as email_service
from app.services.notifications import (
    _format_event_when,
    _run_assignment_digest_pass,
    _run_event_reminder_pass,
    _run_overdue_pass,
    notify_initiative_membership,
)
from app.models.guild import Guild, GuildRole
from app.testing import (
    create_calendar_event,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_user,
)


async def _dispatch(session: AsyncSession) -> None:
    """Drive the reminder pass with the test session. The worker's
    AdminSessionLocal (app_admin) sees the shared users table; mirror that so the
    user-list read isn't RLS-filtered (the gather inside is still member-scoped)."""
    await set_rls_context(session, is_superadmin=True)
    await _run_event_reminder_pass(session, now=datetime.now(timezone.utc))


async def _events_initiative(session: AsyncSession, creator):
    guild = await create_guild(session)
    initiative = await create_initiative(session, guild, creator, name="Reminders")
    initiative.events_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    return guild, initiative


async def _add_attendee(session, initiative, event, user, *, rsvp=RSVPStatus.pending):
    attendee = CalendarEventAttendee(
        calendar_event_id=event.id,
        user_id=user.id,
        guild_id=event.guild_id,
        rsvp_status=rsvp,
    )
    session.add(attendee)
    await session.commit()
    # Reminders are gathered in the attendee's own context, so they must be a
    # guild + initiative member to see the event under RLS (as the real app
    # enforces — you can only attend events in initiatives you belong to).
    guild = await session.get(Guild, event.guild_id)
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.member
    )
    await create_initiative_member(session, initiative, user, role_name="member")


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
    guild, initiative = await _events_initiative(session, creator)
    # Starts in 10 min; with a 15-min lead the reminder is already due.
    start_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    event = await create_calendar_event(
        session,
        initiative,
        creator,
        title="Standup",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, initiative, event, attendee)

    await _dispatch(session)
    assert len(await _reminders_for(session, attendee.id)) == 1

    # Dedup: a second pass must not create another reminder.
    await _dispatch(session)
    assert len(await _reminders_for(session, attendee.id)) == 1

    # The dispatch ledger is guild-scoped; read it under the guild's context.
    await set_rls_context(session, user_id=attendee.id, guild_id=guild.id)
    dispatches = await session.exec(
        select(EventReminderDispatch).where(
            EventReminderDispatch.user_id == attendee.id
        )
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
        session,
        initiative,
        creator,
        title="Sync",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, initiative, event, attendee)

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
        session,
        initiative,
        creator,
        title="Later",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, initiative, event, attendee)

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
        session,
        initiative,
        creator,
        title="Now",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, initiative, event, attendee)

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
        session,
        initiative,
        creator,
        title="Optional",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, initiative, event, attendee, rsvp=RSVPStatus.declined)

    await _dispatch(session)
    assert await _reminders_for(session, attendee.id) == []


@pytest.mark.integration
async def test_notify_initiative_membership_carries_guild_context(
    session: AsyncSession,
):
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


async def _overdue_task_in_new_guild(session: AsyncSession, user: User, *, label: str):
    """Give ``user`` an overdue task assigned to them in a brand-new guild, so a
    user in several guilds has overdue work spread across guild schemas."""
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name=label)
    project = await create_project(session, initiative, user, name=f"{label} Project")
    status = TaskStatus(
        guild_id=guild.id,
        project_id=project.id,
        name="Todo",
        category=TaskStatusCategory.todo,
        position=0,
        is_default=True,
    )
    session.add(status)
    await session.commit()
    await session.refresh(status)
    task = Task(
        guild_id=guild.id,
        project_id=project.id,
        task_status_id=status.id,
        title=f"{label} overdue",
        priority=TaskPriority.medium,
        due_date=datetime.now(timezone.utc) - timedelta(days=1),
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    session.add(TaskAssignee(task_id=task.id, user_id=user.id, guild_id=guild.id))
    await session.commit()
    return guild


@pytest.mark.integration
async def test_overdue_digest_gathers_tasks_across_user_guilds(
    session: AsyncSession, monkeypatch
):
    """The overdue digest must collect a user's overdue tasks from EVERY guild
    they belong to. Under schema-per-guild each guild's tasks live in its own
    schema, so a single public-scoped scan (the old behaviour) would miss all
    but the routed guild — this asserts both guilds' tasks reach the email."""
    user = await create_user(
        session,
        email="multi-overdue@example.com",
        email_overdue_tasks=True,
        overdue_notification_time="00:00",  # always past, so the digest fires
        timezone="UTC",
    )
    await _overdue_task_in_new_guild(session, user, label="Alpha")
    await _overdue_task_in_new_guild(session, user, label="Beta")

    captured: dict = {}

    async def _capture_email(sess, recipient, tasks):
        captured["user_id"] = recipient.id
        captured["titles"] = {t["title"] for t in tasks}

    monkeypatch.setattr(email_service, "send_overdue_tasks_email", _capture_email)

    # Mirror the worker's starting context: its AdminSessionLocal (app_admin) sees
    # the shared users table; the gather inside still scopes guild data per member.
    await set_rls_context(session, is_superadmin=True)
    await _run_overdue_pass(session, now=datetime.now(timezone.utc))

    assert captured.get("user_id") == user.id
    assert captured.get("titles") == {"Alpha overdue", "Beta overdue"}


async def _assignment_item_in_new_guild(
    session: AsyncSession, user: User, *, label: str
):
    """Queue a task-assignment digest item for ``user`` in a brand-new guild."""
    # A prior call left the session in a guild-member context; reset so the new
    # guild INSERT into public.guilds isn't RLS-denied.
    await set_rls_context(session, is_superadmin=True)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name=label)
    project = await create_project(session, initiative, user, name=f"{label} Project")
    status = TaskStatus(
        guild_id=guild.id,
        project_id=project.id,
        name="Todo",
        category=TaskStatusCategory.todo,
        position=0,
        is_default=True,
    )
    session.add(status)
    await session.commit()
    await session.refresh(status)
    task = Task(
        guild_id=guild.id,
        project_id=project.id,
        task_status_id=status.id,
        title=f"{label} task",
        priority=TaskPriority.medium,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    # digest items have no guild_id column, so route by search_path before insert.
    await set_rls_context(session, user_id=user.id, guild_id=guild.id)
    session.add(
        TaskAssignmentDigestItem(
            user_id=user.id,
            task_id=task.id,
            project_id=project.id,
            task_title=task.title,
            project_name=project.name,
            assigned_by_name="Assigner",
        )
    )
    await session.commit()
    return guild


@pytest.mark.integration
async def test_assignment_digest_gathers_items_across_user_guilds(
    session: AsyncSession, monkeypatch
):
    """The task-assignment digest must collect a user's pending items from every
    guild they belong to and mark them processed in each schema — a single
    public-scoped scan (the old behaviour) would see none of them."""
    user = await create_user(
        session, email="multi-digest@example.com"
    )  # opted in by default
    guild_a = await _assignment_item_in_new_guild(session, user, label="Alpha")
    guild_b = await _assignment_item_in_new_guild(session, user, label="Beta")

    captured: dict = {}

    async def _capture_email(sess, recipient, assignments):
        captured["user_id"] = recipient.id
        captured["titles"] = {a["task_title"] for a in assignments}

    monkeypatch.setattr(
        email_service, "send_task_assignment_digest_email", _capture_email
    )

    await set_rls_context(session, is_superadmin=True)
    await _run_assignment_digest_pass(session, now=datetime.now(timezone.utc))

    assert captured.get("user_id") == user.id
    assert captured.get("titles") == {"Alpha task", "Beta task"}

    # Items were marked processed in each guild's own schema.
    for guild_id in (guild_a.id, guild_b.id):
        await set_rls_context(session, user_id=user.id, guild_id=guild_id)
        pending = (
            await session.exec(
                select(TaskAssignmentDigestItem).where(
                    TaskAssignmentDigestItem.processed_at.is_(None)
                )
            )
        ).all()
        assert pending == [], f"guild {guild_id} items not marked processed"


@pytest.mark.integration
async def test_event_reminders_fire_across_a_users_guilds(session: AsyncSession):
    """A user attending due events in several guilds must get a reminder in each.
    Under schema-per-guild the events live in different schemas, so the old
    single public-scoped scan would only ever see the routed guild."""
    attendee = await create_user(
        session, email="multi-reminder@example.com", event_reminder_minutes_before=15
    )
    for label in ("Alpha", "Beta"):
        await set_rls_context(
            session, is_superadmin=True
        )  # permissive for the guild INSERT
        creator = await create_user(session, email=f"organizer-{label}@example.com")
        guild = await create_guild(session, creator=creator)
        initiative = await create_initiative(session, guild, creator, name=label)
        initiative.events_enabled = True
        session.add(initiative)
        await session.commit()
        await session.refresh(initiative)
        # Starts in 10 min; with the attendee's 15-min lead the reminder is due.
        start_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        event = await create_calendar_event(
            session,
            initiative,
            creator,
            title=f"{label} Standup",
            start_at=start_at,
            end_at=start_at + timedelta(minutes=30),
        )
        await _add_attendee(session, initiative, event, attendee)

    await _dispatch(session)

    # Count across guilds: notifications are shared, so view them as superadmin.
    await set_rls_context(session, is_superadmin=True)
    reminders = await _reminders_for(session, attendee.id)
    assert len(reminders) == 2
