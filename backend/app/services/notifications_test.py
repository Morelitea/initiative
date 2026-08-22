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
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
    RSVPStatus,
)
from app.models.tenant.event_reminder_dispatch import EventReminderDispatch
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.task import (
    Task,
    TaskAssignee,
    TaskPriority,
    TaskStatus,
    TaskStatusCategory,
)
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.models.platform.user import User
from app.services import email as email_service
from app.services.platform import push_notifications
from app.services.notifications import (
    ASSIGNMENT_ITEM_RETENTION,
    ASSIGNMENT_MAX_WINDOW,
    ASSIGNMENT_QUIET_PERIOD,
    _format_event_when,
    _run_assignment_digest_pass,
    _run_assignment_gc_pass,
    _run_event_reminder_pass,
    _run_overdue_pass,
    notify_initiative_membership,
)
from app.models.platform.guild import Guild, GuildRole
from app.testing import (
    create_calendar,
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
    await set_rls_context(session)
    await _run_event_reminder_pass(session, now=datetime.now(timezone.utc))


async def _events_initiative(session: AsyncSession, creator):
    guild = await create_guild(session)
    initiative = await create_initiative(session, guild, creator, name="Reminders")
    initiative.calendars_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    calendar = await create_calendar(session, initiative, creator)
    return guild, initiative, calendar


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


def _unsaved_event(
    *, title: str, start_at: datetime, end_at: datetime, all_day: bool
) -> CalendarEvent:
    """In-memory event for the pure-unit formatting tests (never persisted)."""
    return CalendarEvent(
        guild_id=1,
        calendar_id=1,
        created_by=1,
        title=title,
        start_at=start_at,
        end_at=end_at,
        all_day=all_day,
    )


def _unsaved_user(tz: str) -> User:
    """In-memory recipient for the pure-unit formatting tests (never persisted)."""
    return User(
        email_hash="x",
        email_encrypted="x",
        hashed_password="x",
        timezone=tz,
    )


@pytest.mark.unit
def test_format_event_when_localizes_to_recipient_timezone():
    """A timed event renders in the recipient's IANA timezone with its abbrev."""
    event = _unsaved_event(
        title="Sync",
        start_at=datetime(2026, 7, 1, 21, 30, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 1, 22, 30, tzinfo=timezone.utc),
        all_day=False,
    )
    la = _unsaved_user("America/Los_Angeles")
    assert _format_event_when(event, la) == "Wed, Jul 1, 2026 at 2:30 PM PDT"

    utc_user = _unsaved_user("UTC")
    assert _format_event_when(event, utc_user) == "Wed, Jul 1, 2026 at 9:30 PM UTC"


@pytest.mark.unit
def test_format_event_when_all_day_omits_time_and_zone():
    """All-day events show just the date, regardless of recipient timezone."""
    event = _unsaved_event(
        title="Holiday",
        start_at=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 1, 23, 59, tzinfo=timezone.utc),
        all_day=True,
    )
    assert _format_event_when(event, _unsaved_user("Asia/Tokyo")) == "Wed, Jul 1, 2026"


@pytest.mark.unit
def test_format_event_when_falls_back_on_bad_timezone():
    """An unrecognized timezone string falls back to UTC instead of raising."""
    event = _unsaved_event(
        title="Sync",
        start_at=datetime(2026, 7, 1, 21, 30, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 1, 22, 30, tzinfo=timezone.utc),
        all_day=False,
    )
    assert _format_event_when(event, _unsaved_user("Not/AZone")) == (
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
    guild, initiative, calendar = await _events_initiative(session, creator)
    # Starts in 10 min; with a 15-min lead the reminder is already due.
    start_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    event = await create_calendar_event(
        session,
        calendar,
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
    _, initiative, calendar = await _events_initiative(session, creator)
    start_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    event = await create_calendar_event(
        session,
        calendar,
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
    _, initiative, calendar = await _events_initiative(session, creator)
    # Starts in 2 hours; a 15-min lead means the reminder is not yet due.
    start_at = datetime.now(timezone.utc) + timedelta(hours=2)
    event = await create_calendar_event(
        session,
        calendar,
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
    _, initiative, calendar = await _events_initiative(session, creator)
    # Just started (within the grace window); a 0-minute lead is due now.
    start_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    event = await create_calendar_event(
        session,
        calendar,
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
    _, initiative, calendar = await _events_initiative(session, creator)
    start_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    event = await create_calendar_event(
        session,
        calendar,
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
    assert data["target_path"] == f"/i/{initiative.id}"
    assert f"guild_id={guild.id}" in data["smart_link"]


async def _overdue_task_in_new_guild(
    session: AsyncSession,
    user: User,
    *,
    label: str,
    is_template: bool = False,
    project_archived: bool = False,
    task_archived: bool = False,
):
    """Give ``user`` an overdue task assigned to them in a brand-new guild, so a
    user in several guilds has overdue work spread across guild schemas."""
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name=label)
    project = await create_project(
        session,
        initiative,
        user,
        name=f"{label} Project",
        is_template=is_template,
        is_archived=project_archived,
    )
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
        is_archived=task_archived,
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
    await set_rls_context(session)
    await _run_overdue_pass(session, now=datetime.now(timezone.utc))

    assert captured.get("user_id") == user.id
    assert captured.get("titles") == {"Alpha overdue", "Beta overdue"}


def _capture_push(monkeypatch) -> list[dict]:
    """Record every ``send_push_to_user`` call instead of hitting FCM."""
    sent: list[dict] = []

    async def _fake_push(
        *, session, user_id, notification_type, title, body, data=None
    ):
        sent.append(
            {
                "user_id": user_id,
                "type": notification_type,
                "title": title,
                "body": body,
                "data": data or {},
            }
        )
        return 1

    monkeypatch.setattr(push_notifications, "send_push_to_user", _fake_push)
    return sent


@pytest.mark.integration
async def test_overdue_digest_pushes_alongside_email(
    session: AsyncSession, monkeypatch
):
    """Push and email are the same digest on two channels: a user opted into
    both must get both, and the push must carry a tappable deep link."""
    user = await create_user(
        session,
        email="overdue-both@example.com",
        email_overdue_tasks=True,
        push_overdue_tasks=True,
        overdue_notification_time="00:00",
        timezone="UTC",
    )
    await _overdue_task_in_new_guild(session, user, label="Alpha")

    emails: list[int] = []

    async def _capture_email(sess, recipient, tasks):
        emails.append(recipient.id)

    monkeypatch.setattr(email_service, "send_overdue_tasks_email", _capture_email)
    pushes = _capture_push(monkeypatch)

    await set_rls_context(session)
    await _run_overdue_pass(session, now=datetime.now(timezone.utc))

    assert emails == [user.id]
    assert len(pushes) == 1
    push = pushes[0]
    assert push["user_id"] == user.id
    assert push["type"] == NotificationType.overdue_tasks
    assert "Alpha overdue" in push["body"]
    # The digest spans guilds, so the tap lands on the cross-guild My Tasks
    # list — no guild_id, which is what tells the app not to switch guilds.
    assert push["data"]["target_path"] == "/"
    assert "guild_id" not in push["data"]


@pytest.mark.integration
async def test_overdue_digest_pushes_when_email_opted_out(
    session: AsyncSession, monkeypatch
):
    """Turning the email off must not silence the push — the two toggles are
    independent, and the day's send is still stamped so it fires once."""
    user = await create_user(
        session,
        email="overdue-push-only@example.com",
        email_overdue_tasks=False,
        push_overdue_tasks=True,
        overdue_notification_time="00:00",
        timezone="UTC",
    )
    await _overdue_task_in_new_guild(session, user, label="Alpha")

    async def _fail_email(sess, recipient, tasks):  # pragma: no cover
        raise AssertionError("email must not be sent to an opted-out user")

    monkeypatch.setattr(email_service, "send_overdue_tasks_email", _fail_email)
    pushes = _capture_push(monkeypatch)

    now = datetime.now(timezone.utc)
    await set_rls_context(session)
    await _run_overdue_pass(session, now=now)
    assert len(pushes) == 1

    # Second pass the same day is a no-op (the stamp landed on the push alone).
    session.expunge_all()
    await set_rls_context(session)
    await _run_overdue_pass(session, now=now + timedelta(minutes=5))
    assert len(pushes) == 1

    refreshed = (
        await session.exec(select(User).where(User.id == user.id))
    ).one_or_none()
    assert refreshed.last_overdue_notification_at is not None


@pytest.mark.integration
async def test_overdue_digest_skips_push_when_opted_out(
    session: AsyncSession, monkeypatch
):
    """A user who wants only the email gets only the email."""
    user = await create_user(
        session,
        email="overdue-email-only@example.com",
        email_overdue_tasks=True,
        push_overdue_tasks=False,
        overdue_notification_time="00:00",
        timezone="UTC",
    )
    await _overdue_task_in_new_guild(session, user, label="Alpha")

    async def _capture_email(sess, recipient, tasks):
        return None

    monkeypatch.setattr(email_service, "send_overdue_tasks_email", _capture_email)
    pushes = _capture_push(monkeypatch)

    await set_rls_context(session)
    await _run_overdue_pass(session, now=datetime.now(timezone.utc))

    assert pushes == []


@pytest.mark.integration
async def test_overdue_digest_skips_template_projects(
    session: AsyncSession, monkeypatch
):
    """Tasks living in a template project are blueprints, not work — their due
    dates must never reach the digest (email or push)."""
    user = await create_user(
        session,
        email="template-overdue@example.com",
        email_overdue_tasks=True,
        push_overdue_tasks=True,
        overdue_notification_time="00:00",
        timezone="UTC",
    )
    await _overdue_task_in_new_guild(session, user, label="Real")
    await _overdue_task_in_new_guild(session, user, label="Template", is_template=True)

    captured: dict = {}

    async def _capture_email(sess, recipient, tasks):
        captured["titles"] = {t["title"] for t in tasks}

    monkeypatch.setattr(email_service, "send_overdue_tasks_email", _capture_email)
    pushes = _capture_push(monkeypatch)

    await set_rls_context(session)
    await _run_overdue_pass(session, now=datetime.now(timezone.utc))

    assert captured.get("titles") == {"Real overdue"}
    assert len(pushes) == 1
    assert "Template overdue" not in pushes[0]["body"]


@pytest.mark.integration
async def test_overdue_digest_skips_archived_projects_and_tasks(
    session: AsyncSession, monkeypatch
):
    """Archiving is how a user says work is off their plate — an archived
    project, or an archived task in a live project, is not a deadline the
    digest should still be chasing."""
    user = await create_user(
        session,
        email="archived-overdue@example.com",
        email_overdue_tasks=True,
        push_overdue_tasks=True,
        overdue_notification_time="00:00",
        timezone="UTC",
    )
    await _overdue_task_in_new_guild(session, user, label="Live")
    await _overdue_task_in_new_guild(
        session, user, label="ArchivedProject", project_archived=True
    )
    await _overdue_task_in_new_guild(
        session, user, label="ArchivedTask", task_archived=True
    )

    captured: dict = {}

    async def _capture_email(sess, recipient, tasks):
        captured["titles"] = {t["title"] for t in tasks}

    monkeypatch.setattr(email_service, "send_overdue_tasks_email", _capture_email)
    pushes = _capture_push(monkeypatch)

    await set_rls_context(session)
    await _run_overdue_pass(session, now=datetime.now(timezone.utc))

    assert captured.get("titles") == {"Live overdue"}
    assert len(pushes) == 1
    assert "ArchivedProject overdue" not in pushes[0]["body"]
    assert "ArchivedTask overdue" not in pushes[0]["body"]


async def _assignment_item_in_new_guild(
    session: AsyncSession, user: User, *, label: str
):
    """Queue a task-assignment digest item for ``user`` in a brand-new guild."""
    # A prior call left the session in a guild-member context; reset so the new
    # guild INSERT into public.guilds isn't RLS-denied.
    await set_rls_context(session)
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

    await set_rls_context(session)
    # Past the quiet period, so the items have settled and the digest is due.
    await _run_assignment_digest_pass(
        session, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
    )

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
async def test_assignment_digest_waits_for_the_flurry_to_end(
    session: AsyncSession, monkeypatch
):
    """The whole point of a digest: it must not fire on the first item while
    more are still landing. The old behaviour emailed immediately and then
    locked out for an hour, so a burst arrived as one mail plus a long delay."""
    user = await create_user(session, email="debounce@example.com")
    await _assignment_item_in_new_guild(session, user, label="Alpha")

    sent: list[int] = []

    async def _capture_email(sess, recipient, assignments):
        sent.append(len(assignments))

    monkeypatch.setattr(
        email_service, "send_task_assignment_digest_email", _capture_email
    )
    _capture_push(monkeypatch)

    # Item just landed — still accumulating, nothing goes out.
    await set_rls_context(session)
    await _run_assignment_digest_pass(session, now=datetime.now(timezone.utc))
    assert sent == []

    # A second item lands, and the quiet period restarts from it: the run at
    # what would have been the first item's deadline must still hold.
    await _assignment_item_in_new_guild(session, user, label="Beta")
    session.expunge_all()
    await set_rls_context(session)
    await _run_assignment_digest_pass(
        session, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD / 2
    )
    assert sent == []

    # Once it has been quiet, both items ship together.
    session.expunge_all()
    await set_rls_context(session)
    await _run_assignment_digest_pass(
        session, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
    )
    assert sent == [2]


@pytest.mark.integration
async def test_assignment_digest_caps_a_steady_trickle(
    session: AsyncSession, monkeypatch
):
    """A trickle that never goes quiet must not defer the digest forever —
    the max window is what stops the quiet period from being gamed."""
    user = await create_user(session, email="trickle@example.com")
    await _assignment_item_in_new_guild(session, user, label="Alpha")

    sent: list[int] = []

    async def _capture_email(sess, recipient, assignments):
        sent.append(len(assignments))

    monkeypatch.setattr(
        email_service, "send_task_assignment_digest_email", _capture_email
    )
    _capture_push(monkeypatch)

    # An item that landed a moment ago would normally hold the digest, but the
    # window opened long enough ago that it ships regardless.
    await set_rls_context(session)
    await _run_assignment_digest_pass(
        session, now=datetime.now(timezone.utc) + ASSIGNMENT_MAX_WINDOW
    )
    assert sent == [1]


@pytest.mark.integration
async def test_assignment_digest_sends_both_channels_together(
    session: AsyncSession, monkeypatch
):
    """Email and push now ship from the same pass on the same trigger, so the
    two channels can't tell different stories about the same assignments."""
    user = await create_user(session, email="digest-both@example.com")
    await _assignment_item_in_new_guild(session, user, label="Alpha")
    await _assignment_item_in_new_guild(session, user, label="Beta")

    emails: list[int] = []

    async def _capture_email(sess, recipient, assignments):
        emails.append(len(assignments))

    monkeypatch.setattr(
        email_service, "send_task_assignment_digest_email", _capture_email
    )
    pushes = _capture_push(monkeypatch)

    await set_rls_context(session)
    await _run_assignment_digest_pass(
        session, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
    )

    assert emails == [2]
    assert len(pushes) == 1
    # A multi-task digest spans guilds, so it lands on My Tasks.
    assert pushes[0]["data"]["count"] == "2"
    assert pushes[0]["data"]["target_path"] == "/"
    assert "guild_id" not in pushes[0]["data"]


@pytest.mark.integration
async def test_assignment_digest_of_one_deep_links_to_the_task(
    session: AsyncSession, monkeypatch
):
    """A digest of one has an unambiguous destination, so it keeps the deep
    link the old per-task push had."""
    user = await create_user(session, email="digest-one@example.com")
    guild = await _assignment_item_in_new_guild(session, user, label="Alpha")

    async def _capture_email(sess, recipient, assignments):
        return None

    monkeypatch.setattr(
        email_service, "send_task_assignment_digest_email", _capture_email
    )
    pushes = _capture_push(monkeypatch)

    await set_rls_context(session)
    await _run_assignment_digest_pass(
        session, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
    )

    assert len(pushes) == 1
    assert pushes[0]["data"]["guild_id"] == str(guild.id)
    assert pushes[0]["data"]["target_path"].startswith("/go/task/")


@pytest.mark.integration
async def test_assignment_digest_pushes_when_email_opted_out(
    session: AsyncSession, monkeypatch
):
    """Queueing is gated on either channel, so a push-only user still gets the
    digest — previously the queue row was written only for email."""
    user = await create_user(
        session,
        email="digest-push-only@example.com",
        email_task_assignment=False,
        push_task_assignment=True,
    )
    await _assignment_item_in_new_guild(session, user, label="Alpha")

    async def _fail_email(sess, recipient, assignments):  # pragma: no cover
        raise AssertionError("email must not be sent to an opted-out user")

    monkeypatch.setattr(email_service, "send_task_assignment_digest_email", _fail_email)
    pushes = _capture_push(monkeypatch)

    await set_rls_context(session)
    await _run_assignment_digest_pass(
        session, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
    )

    assert len(pushes) == 1


@pytest.mark.integration
async def test_assignment_digest_honours_a_preference_changed_mid_pass(
    session: AsyncSession, monkeypatch
):
    """The pass snapshots its candidates, then spends time routing through each
    guild. A channel switched off in that gap must not still be delivered to —
    the send has to read the reloaded row, not the snapshot."""
    user = await create_user(session, email="pref-race@example.com")
    await _assignment_item_in_new_guild(session, user, label="Alpha")

    async def _fail_email(sess, recipient, assignments):  # pragma: no cover
        raise AssertionError("email must not be sent after opting out")

    monkeypatch.setattr(email_service, "send_task_assignment_digest_email", _fail_email)
    pushes = _capture_push(monkeypatch)

    # Turn the email off after the items were queued — as a request handled
    # while the worker is mid-gather would.
    session.expunge_all()
    await set_rls_context(session, user_id=user.id)
    fresh = (await session.exec(select(User).where(User.id == user.id))).one()
    fresh.email_task_assignment = False
    session.add(fresh)
    await session.commit()

    session.expunge_all()
    await set_rls_context(session)
    await _run_assignment_digest_pass(
        session, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
    )

    assert len(pushes) == 1  # push is still on, and still delivers


@pytest.mark.integration
async def test_assignment_gc_drops_items_past_retention(session: AsyncSession):
    """Digest items accumulated forever — nothing ever deleted them. The sweep
    clears anything past the retention window, sent or not, so an orphaned
    queue can't grow without bound either."""
    user = await create_user(session, email="digest-gc@example.com")
    guild = await _assignment_item_in_new_guild(session, user, label="Alpha")

    async def _row_count() -> int:
        session.expunge_all()
        await set_rls_context(session, user_id=user.id, guild_id=guild.id)
        rows = (await session.exec(select(TaskAssignmentDigestItem))).all()
        return len(rows)

    assert await _row_count() == 1

    # Well inside the window: nothing is touched.
    session.expunge_all()
    await set_rls_context(session)
    await _run_assignment_gc_pass(session, now=datetime.now(timezone.utc))
    assert await _row_count() == 1

    session.expunge_all()
    await set_rls_context(session)
    await _run_assignment_gc_pass(
        session, now=datetime.now(timezone.utc) + ASSIGNMENT_ITEM_RETENTION
    )
    assert await _row_count() == 0


@pytest.mark.integration
async def test_event_reminders_fire_across_a_users_guilds(session: AsyncSession):
    """A user attending due events in several guilds must get a reminder in each.
    Under schema-per-guild the events live in different schemas, so the old
    single public-scoped scan would only ever see the routed guild."""
    attendee = await create_user(
        session, email="multi-reminder@example.com", event_reminder_minutes_before=15
    )
    for label in ("Alpha", "Beta"):
        await set_rls_context(session)  # permissive for the guild INSERT
        creator = await create_user(session, email=f"organizer-{label}@example.com")
        guild = await create_guild(session, creator=creator)
        initiative = await create_initiative(session, guild, creator, name=label)
        initiative.calendars_enabled = True
        session.add(initiative)
        await session.commit()
        await session.refresh(initiative)
        calendar = await create_calendar(session, initiative, creator)
        # Starts in 10 min; with the attendee's 15-min lead the reminder is due.
        start_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        event = await create_calendar_event(
            session,
            calendar,
            creator,
            title=f"{label} Standup",
            start_at=start_at,
            end_at=start_at + timedelta(minutes=30),
        )
        await _add_attendee(session, initiative, event, attendee)

    await _dispatch(session)

    # Count across guilds: notifications are shared, so read them on the
    # unrouted system engine.
    await set_rls_context(session)
    reminders = await _reminders_for(session, attendee.id)
    assert len(reminders) == 2
