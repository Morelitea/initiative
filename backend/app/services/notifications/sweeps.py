"""The time-driven notices: overdue tasks, hold summaries, event reminders.

Nothing changed when these fire — the clock moved — so each is a sweep that
starts from what is due in each community and goes near nobody else.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import SYSTEM_SATISFIED, SystemSessionLocal, set_rls_context
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.core.notification_categories import (
    Channel,
    NotificationCategory,
    category_of,
    sample_type,
)
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
    RSVPStatus,
)
from app.models.tenant.event_reminder_dispatch import EventReminderDispatch
from app.models.platform.user import User
from app.models.platform.user_notification_prefs import (
    EmailCadence,
    UserNotificationPrefs,
)
from app.services.platform import accounts as accounts_service
from app.models.platform.notification import Notification, NotificationType
from app.services import email as email_service
from app.services.platform import email_outbox
from app.services.platform import notification_policy
from app.services.platform import notification_prefs
from app.services.platform import push_notifications
from app.services.notifications.delivery import (
    MY_TASKS_TARGET_PATH,
    _build_smart_link,
    _channels,
    _nt,
    _recipient_locale,
    _resolve_timezone,
    _task_target_path,
)
from app.services.notifications.digests import _digest_batch, wants_digest
from app.services.notifications.guild_walk import per_guild
from app.services.notifications.notifiers import notify_event_reminder

logger = logging.getLogger(__name__)


OVERDUE_POLL_SECONDS = 300


# A summary goes out when a hold lifts, so the poll only has to be finer than
# the grace period it is bounded by.
HOLD_SUMMARY_POLL_SECONDS = 600


EVENT_REMINDER_POLL_SECONDS = 60


# Events that started within this window are still eligible, so a 0-minute
# ("at start") reminder fires on the next poll rather than being missed.
EVENT_REMINDER_GRACE = timedelta(minutes=5)


def _overdue_assignments(*columns: Any) -> Any:
    """Assigned, unfinished, past-due tasks in the routed guild schema.

    Template projects are excluded: their tasks are blueprints, not work, so a
    due date on one is never actually overdue. Archived projects and archived
    tasks are excluded for the same reason — archiving is how a user says the
    work is off their plate, so a past due date on one is not a deadline the
    digest should still be chasing. This matches the filters the cross-guild My
    Tasks list already applies.
    """
    return (
        select(*columns)
        .select_from(Task)
        .join(Project, Task.project_id == Project.id)
        .join(Initiative, Project.initiative_id == Initiative.id)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .join(TaskStatus, Task.task_status_id == TaskStatus.id)
        .where(
            Project.is_template.is_(False),
            Project.archived_at.is_(None),
            Task.archived_at.is_(None),
            Task.due_date.is_not(None),
            Task.due_date < datetime.now(timezone.utc),
            TaskStatus.category != TaskStatusCategory.done,
        )
    )


async def _overdue_tasks_for_user(
    session: AsyncSession, user_id: int, guild_id: int
) -> list[dict]:
    """Overdue tasks assigned to the user *in the currently routed guild schema*.

    Run once per guild via ``gather_across_guilds`` (the session is routed into
    each of the user's guilds in turn), so it only ever sees one guild's rows.
    """
    stmt = (
        _overdue_assignments(Task, Project.name, Project.id)
        .where(TaskAssignee.user_id == user_id)
        .order_by(Task.due_date.asc())
    )
    result = await session.exec(stmt)
    rows = result.all()
    tasks: list[dict] = []
    for row in rows:
        task, project_name, project_id = row
        target_path = _task_target_path(task.id, project_id)
        tasks.append(
            {
                "title": task.title,
                "project_name": project_name,
                "due_date": task.due_date.strftime("%Y-%m-%d %H:%M UTC")
                if task.due_date
                else "N/A",
                "link": _build_smart_link(target_path=target_path, guild_id=guild_id),
                "guild_id": guild_id,
            }
        )
    return tasks


async def _accounts_with_overdue_tasks(session: AsyncSession) -> dict[int, list[int]]:
    """Who has an overdue task anywhere, and in which communities:
    ``{user_id: [guild_id, …]}``."""
    found: dict[int, list[int]] = {}

    async def _visit(routed: AsyncSession, guild_id: int) -> None:
        for user_id in (
            await routed.exec(_overdue_assignments(TaskAssignee.user_id).distinct())
        ).scalars():
            found.setdefault(user_id, []).append(guild_id)

    await per_guild(session, _visit)
    return found


async def _send_overdue_push(
    session: AsyncSession, user: User, tasks: list[dict]
) -> bool:
    """Push the overdue digest to the user's devices. Returns whether it landed.

    The digest spans every guild the user belongs to, so the tap lands on My
    Tasks — the cross-guild list — rather than on any one task. It carries no
    ``guild_id`` for that reason; the mobile tap handler treats a bare
    ``target_path`` as an app-level route.
    """
    locale = _recipient_locale(user)
    if any(item.get("redacted") for item in tasks):
        title, body = notification_policy.redacted_push(
            NotificationType.overdue_tasks, locale
        )
    else:
        title = _nt("task.overdue.title", locale)
        body = _nt(
            "task.overdue.body", locale, count=len(tasks), title=tasks[0]["title"]
        )
    data = {
        "type": NotificationType.overdue_tasks.value,
        "count": str(len(tasks)),
        "target_path": MY_TASKS_TARGET_PATH,
    }
    try:
        sent = await push_notifications.send_push_to_user(
            session=session,
            user_id=user.id,
            notification_type=NotificationType.overdue_tasks,
            locale=locale,
            title=title,
            body=body,
            data=data,
        )
    except Exception as exc:
        logger.error("Failed to send overdue push: %s", exc, exc_info=True)
        return False
    return sent > 0


async def _run_overdue_pass(session: AsyncSession, *, now: datetime) -> None:
    """Send overdue-task digests to opted-in users as of ``now``.

    Split out from ``process_overdue_notifications`` so tests can drive it with
    the test session (the worker opens its own ``SystemSessionLocal``). Starts
    from the work: each community is asked once who has an overdue task, and
    only those accounts are read. Each one's tasks are then gathered from their
    own guild schemas with their membership context — no all-guild access.

    Both channels ship from this one pass: the digest email and a push. A user
    opted into either channel is a candidate, so turning email off doesn't
    silence push.
    """
    overdue = await _accounts_with_overdue_tasks(session)
    if not overdue:
        logger.debug("overdue-digest: nothing overdue")
        return
    users = (
        (await session.exec(select(User).where(User.id.in_(list(overdue)))))
        .scalars()
        .all()
    )
    # Settings are sparse and default to on, so filtering happens here through
    # the same resolution the live path uses rather than as a second copy of it
    # expressed in SQL.
    all_prefs = await notification_prefs.load_prefs_for(session, [u.id for u in users])
    users = [
        u
        for u in users
        if wants_digest(all_prefs.get(u.id), NotificationCategory.due_dates)
    ]
    if not users:
        logger.debug("overdue-digest: no users opted in")
        return
    # Capture plain fields up front: gathering routes per guild and expunges the
    # identity map, which would detach these ORM rows. The channel preferences
    # are deliberately NOT snapshotted here; they are read off the freshly
    # reloaded row at delivery time.
    candidates = [
        (
            u.id,
            u.timezone,
            notification_prefs.email_schedule(all_prefs.get(u.id)),
            u.last_overdue_notification_at,
        )
        for u in users
    ]
    for user_id, user_tz, schedule, last_at in candidates:
        tz = _resolve_timezone(user_tz)
        now_local = now.astimezone(tz)
        try:
            hour, minute = map(int, schedule.at.split(":"))
        except ValueError:
            hour, minute = 21, 0
        target_local = now_local.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if now_local < target_local:
            continue
        # A weekly cadence gets this with its weekly mail rather than daily:
        # somebody who asked to hear from us once a week did not ask to be
        # chased about the same tasks on the other six days.
        if (
            schedule.cadence is EmailCadence.weekly
            and now_local.isoweekday() != schedule.weekday
        ):
            continue
        if last_at and last_at.astimezone(tz).date() == now_local.date():
            continue
        # User-scoped: visit each of the user's guild schemas with their own
        # membership context (no all-guild access) and collect their overdue tasks.
        guild_ids = await member_guild_ids(
            session, user_id, restrict_to=overdue[user_id]
        )
        tasks = await gather_across_guilds(
            session,
            user_id,
            guild_ids,
            # _uid default-binds user_id so the closure doesn't capture the loop
            # variable by reference (B023).
            lambda routed, gid, _uid=user_id: _overdue_tasks_for_user(
                routed, _uid, gid
            ),
            satisfied_providers=SYSTEM_SATISFIED,
        )
        if not tasks:
            continue
        # Re-load the user (the gather expunged it) to send + stamp it. The
        # email/stamp touch only shared tables, so the user-only context is fine.
        session.expunge_all()
        await set_rls_context(session, user_id=user_id)
        user = (
            await session.exec(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if (
            user is None
        ):  # deleted between the snapshot and now — skip, don't abort the pass
            continue
        # Only stamp once something actually went out, so a channel that is
        # merely unconfigured (no SMTP, no FCM) re-tries on the next poll
        # instead of burning the user's one digest for the day. Preferences are
        # re-read off the row just reloaded, not the snapshot taken before the
        # cross-guild gather, so a channel switched off meanwhile stays quiet.
        delivered = False
        channels = await _channels(
            session, user, notification_type=NotificationType.overdue_tasks
        )
        email_tasks, push_tasks = await _digest_batch(session, tasks)
        if channels.email and email_tasks:
            delivered = await email_outbox.enqueue(
                session,
                user,
                category=NotificationCategory.due_dates,
                prefs=channels.prefs,
                pieces=email_service.overdue_tasks_pieces(user, email_tasks),
            )
            if delivered:
                logger.info(
                    "overdue-digest: queued %d overdue task(s) for user %s",
                    len(email_tasks),
                    user_id,
                )
            else:
                logger.warning(
                    "SMTP not configured; skipping overdue digest for %s", user_id
                )
        if channels.push and push_tasks:
            delivered = await _send_overdue_push(session, user, push_tasks) or delivered
        if not delivered:
            continue
        user.last_overdue_notification_at = now
        session.add(user)
        await session.commit()


async def process_overdue_notifications() -> None:
    async with SystemSessionLocal() as session:
        await _run_overdue_pass(session, now=datetime.now(timezone.utc))


# Holds: one summary when a hold lifts
#
# Two of the three holds end with somebody coming back to news they have not
# seen: a pause, and the nightly quiet-hours window. Both say the same thing
# when they lift, so they say it through one pass.
#
# What arrives is split by channel, and deliberately so. The **email** is the
# content itself — the held rows drain out of the outbox as one digest, which
# is what they were waiting for, and nothing here composes it. The **push** is
# a count, because a push is a thing you glance at and a fortnight of headlines
# is not glanceable. The bell needs neither: it has been collecting all along.
#
# The third hold, being at the keyboard, has nothing to summarise. They were
# here; the bell told them.


async def _hold_summary_rows(
    session: AsyncSession, *, user_id: int, since: datetime, until: datetime
) -> list[tuple[NotificationCategory, int | None, int]]:
    """What was held back, grouped by category and community.

    A query, not a queue. Everything suppressed while the hold was on is
    already sitting in the inbox unread and stamped inside the stretch, so
    there is nothing else to record and nothing to drain.
    """
    stmt = (
        select(
            Notification.type,
            Notification.guild_id,
            func.count().label("total"),
        )
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
            Notification.created_at >= since,
            Notification.created_at < until,
        )
        .group_by(Notification.type, Notification.guild_id)
    )
    rows = (await session.exec(stmt)).all()
    grouped: dict[tuple[NotificationCategory, int | None], int] = {}
    for notification_type, guild_id, total in rows:
        key = (category_of(NotificationType(notification_type)), guild_id)
        grouped[key] = grouped.get(key, 0) + int(total)
    return [
        (category, guild_id, total) for (category, guild_id), total in grouped.items()
    ]


def _rows_for_push(
    rows: list[tuple[NotificationCategory, int | None, int]],
    *,
    prefs: Mapping[str, Any],
) -> list[tuple[NotificationCategory, int | None, int]]:
    """The part of a summary the push may carry.

    Resolved per (category, community) exactly as the live path resolves it, so
    a summary never counts something the account has switched off, and a
    summary with nothing left to say is not sent at all.
    """
    return [
        (category, guild_id, count)
        for category, guild_id, count in rows
        if notification_prefs.wants(
            prefs,
            notification_type=sample_type(category),
            channel=Channel.push,
            guild_id=guild_id,
        )
    ]


def _section_of(prefs: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = prefs.get(key)
    return value if isinstance(value, Mapping) else {}


def _lift_stamps(prefs: Mapping[str, Any]) -> dict[str, str]:
    """When each kind of hold was last summarised.

    Per kind, because a pause and a quiet-hours window end independently and
    one covering the other's stretch would strand a summary that never went.
    """
    raw = _section_of(_section_of(prefs, "holds"), "last_summary_at")
    return {k: v for k, v in raw.items() if isinstance(v, str)}


def _covered(
    stamps: Mapping[str, str],
    kind: notification_prefs.HoldKind,
    closed: datetime,
) -> bool:
    raw = stamps.get(kind.value)
    if not isinstance(raw, str):
        return False
    try:
        return datetime.fromisoformat(raw) >= closed
    except ValueError:
        return False


async def _record_lift(
    session: AsyncSession,
    *,
    user_id: int,
    lift: notification_prefs.Lift,
    summarised: bool,
) -> None:
    """Write down that this hold has been dealt with.

    The document is re-read here rather than reused from the top of the pass:
    sending is network I/O, the account may have changed a setting while it
    ran, and saving replaces the whole document — so a copy loaded before the
    send would carry their change back out.

    A lapsed pause is cleared whether or not its push went, and only the push
    is at stake: the content itself left through the outbox when the hold
    lifted, so a failed push costs the count, never the news. A quiet-hours
    window keeps a stamp instead, because the window comes round again.
    """
    fresh = await notification_prefs.load_prefs(session, user_id)
    if lift.kind is notification_prefs.HoldKind.pause:
        fresh.pop("pause", None)
    elif summarised:
        holds = dict(_section_of(fresh, "holds"))
        stamps = dict(_lift_stamps(fresh))
        stamps[lift.kind.value] = lift.closed.isoformat()
        holds["last_summary_at"] = stamps
        fresh["holds"] = holds
    else:
        return
    await notification_prefs.save_prefs(session, user_id, fresh)
    await session.commit()


async def _run_hold_summary_pass(session: AsyncSession, *, now: datetime) -> None:
    """Tell each account what it missed, once, when a hold lifts.

    Only accounts that have set a hold can have one lift, so only they are
    read: a pause or a quiet-hours window is a key in the settings document,
    and an account without either has nothing to summarise.
    """
    holders = select(UserNotificationPrefs.user_id).where(
        UserNotificationPrefs.prefs.has_any(  # type: ignore[union-attr]
            postgresql.array(
                [
                    notification_prefs.HoldKind.pause.value,
                    notification_prefs.HoldKind.quiet_hours.value,
                ]
            )
        )
    )
    users = (
        (await session.exec(select(User).where(User.id.in_(holders)))).scalars().all()
    )
    all_prefs = await notification_prefs.load_prefs_for(
        session, [user.id for user in users]
    )
    for user in users:
        prefs = all_prefs.get(user.id)
        if not prefs:
            continue
        lift = notification_prefs.last_lift(prefs, tz_name=user.timezone, now=now)
        if lift is None:
            continue
        if _covered(_lift_stamps(prefs), lift.kind, lift.closed):
            continue

        rows = _rows_for_push(
            await _hold_summary_rows(
                session, user_id=user.id, since=lift.opened, until=lift.closed
            ),
            prefs=prefs,
        )
        if not rows:
            # Nothing the push may carry is a covered summary, not one to
            # reconsider on every poll.
            await _record_lift(session, user_id=user.id, lift=lift, summarised=True)
            continue

        locale = _recipient_locale(user)
        key = (
            "holds.pause"
            if lift.kind is notification_prefs.HoldKind.pause
            else "quietHours.summary"
        )
        summarised = False
        try:
            summarised = bool(
                await push_notifications.send_push_to_user(
                    session=session,
                    user_id=user.id,
                    notification_type=sample_type(rows[0][0]),
                    locale=locale,
                    title=_nt(f"{key}.title", locale),
                    body=_nt(
                        f"{key}.body",
                        locale,
                        count=sum(count for _, _, count in rows),
                    ),
                    data={
                        "type": f"{lift.kind.value}_summary",
                        "target_path": "/notifications",
                    },
                )
            )
        except Exception as exc:
            logger.error("Failed to push hold summary: %s", exc, exc_info=True)

        await _record_lift(session, user_id=user.id, lift=lift, summarised=summarised)


async def process_hold_summaries() -> None:
    async with SystemSessionLocal() as session:
        await _run_hold_summary_pass(session, now=datetime.now(timezone.utc))


async def _run_event_reminder_pass(session: AsyncSession, *, now: datetime) -> None:
    """Dispatch any reminders due as of ``now``.

    Starts from what is due: each community is asked once which opted-in
    attendees have a reminder due and unsent. Only those accounts are then
    routed into only those communities, with their own membership context (no
    superadmin), to dispatch reminders for the events they attend there. Split out from ``process_event_reminders``
    so tests can drive it with the test session.
    """
    from app.api.deps import GuildAccessError, establish_guild_access

    horizon = now + timedelta(days=1)
    # Allow events that started within the grace window so a 0-minute
    # ("at the time of the event") reminder still fires on the next poll.
    lower = now - EVENT_REMINDER_GRACE
    # Asked of the system engine, not of this session: the sweep routes into
    # each guild's schema in turn, and a routed session cannot read an
    # account's preferences.
    users = await accounts_service.load_event_reminder_optins()
    lead = {
        account.id: timedelta(minutes=account.event_reminder_minutes_before)
        for account in users
        if account.id is not None and account.event_reminder_minutes_before is not None
    }
    if not lead:
        return
    # Each community is asked once which of those accounts have a reminder due
    # and not yet sent; only they are routed into it below.
    due_in: dict[int, set[int]] = {}

    async def _visit(routed: AsyncSession, guild_id: int) -> None:
        rows = (
            await routed.exec(
                select(
                    CalendarEventAttendee.user_id,
                    CalendarEvent.start_at,
                )
                .join(
                    CalendarEvent,
                    CalendarEventAttendee.calendar_event_id == CalendarEvent.id,
                )
                .where(
                    CalendarEventAttendee.rsvp_status != RSVPStatus.declined,
                    CalendarEvent.deleted_at.is_(None),
                    CalendarEvent.start_at > lower,
                    CalendarEvent.start_at <= horizon,
                    ~select(EventReminderDispatch.id)
                    .where(
                        EventReminderDispatch.event_id == CalendarEvent.id,
                        EventReminderDispatch.user_id == CalendarEventAttendee.user_id,
                        EventReminderDispatch.event_start_at == CalendarEvent.start_at,
                    )
                    .exists(),
                )
            )
        ).all()
        for user_id, start_at in rows:
            if user_id in lead and start_at - lead[user_id] <= now:
                due_in.setdefault(user_id, set()).add(guild_id)

    await per_guild(session, _visit)
    for account in users:
        user_id = account.id
        if user_id not in due_in:
            continue
        for guild_id in await member_guild_ids(
            session, user_id, restrict_to=sorted(due_in[user_id])
        ):
            session.expunge_all()
            # Through the seam, as the account whose reminders these are: what
            # the sweep may see of a community is what that account may see.
            try:
                await establish_guild_access(
                    session,
                    account,
                    guild_id,
                    satisfied_providers=SYSTEM_SATISFIED,
                )
            except GuildAccessError:
                continue
            events = (
                (
                    await session.exec(
                        select(CalendarEvent)
                        .join(
                            CalendarEventAttendee,
                            CalendarEventAttendee.calendar_event_id == CalendarEvent.id,
                        )
                        .where(
                            CalendarEventAttendee.user_id == user_id,
                            CalendarEventAttendee.rsvp_status != RSVPStatus.declined,
                            CalendarEvent.deleted_at.is_(None),
                            CalendarEvent.start_at > lower,
                            CalendarEvent.start_at <= horizon,
                        )
                    )
                )
                .scalars()
                .all()
            )
            # Capture before the per-reminder commits expire/detach the rows.
            due = [
                (e.id, e.start_at, guild_id)
                for e in events
                if e.start_at - lead[user_id] <= now
            ]
            for event_id, start_at, ev_guild_id in due:
                existing = await session.exec(
                    select(EventReminderDispatch.id).where(
                        EventReminderDispatch.event_id == event_id,
                        EventReminderDispatch.user_id == user_id,
                        EventReminderDispatch.event_start_at == start_at,
                    )
                )
                if existing.first() is not None:
                    continue
                # Reserve the dedup row before dispatching (reserve-then-send), so
                # a send that outlives a failed ledger commit can't double-fire.
                session.add(
                    EventReminderDispatch(
                        event_id=event_id, user_id=user_id, event_start_at=start_at
                    )
                )
                await session.commit()
                recipient = await accounts_service.load_one(user_id)
                event = (
                    await session.exec(
                        select(CalendarEvent).where(CalendarEvent.id == event_id)
                    )
                ).scalar_one_or_none()
                if recipient is None or event is None:
                    continue  # deleted mid-run; dedup row stays so we don't retry
                await notify_event_reminder(
                    session, recipient=recipient, event=event, guild_id=ev_guild_id
                )
                await session.commit()


async def process_event_reminders() -> None:
    """Dispatch lead-time reminders for upcoming calendar events.

    Polled by the background worker. Considers events starting within the next
    day (the widest lead preset) whose attendees opted into reminders, and
    fires once per (event, user, start time) — keyed on ``start_at`` so a
    reschedule re-arms the reminder. Attendees who RSVP'd ``declined`` are
    skipped.
    """
    async with SystemSessionLocal() as session:
        await _run_event_reminder_pass(session, now=datetime.now(timezone.utc))
