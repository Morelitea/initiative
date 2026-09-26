"""Notifications: who hears about what, and how.

:func:`notify` is the one way a notice reaches people — a bell line each, then
email and push — and it decides who may hear it from what the notice is about.
Below it: the reaction and assignment notices (their bell line is written at
once, email and push wait for a digest), the digests themselves, and the
time-driven sweeps (overdue tasks, hold summaries, event reminders), each of
which starts from what is waiting in each community and claims its work before
sending it.

A notification is read on the cross-guild ``/me/notifications`` surface, away
from the guild it was written in, so the people it names are named by their
handle rather than by whatever that one guild renders.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from urllib.parse import quote

from sqlalchemy import column as sa_column
from sqlalchemy import delete, func, or_, select
from sqlalchemy import table as sa_table
from sqlalchemy import update as sa_update
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.core.email_i18n import email_t, translate
from app.core.notification_categories import (
    Channel,
    NotificationCategory,
    category_of,
    sample_type,
)
from app.core.tools import COMMENT_TARGETS, Tool
from app.core.user_display import handle_of
from app.db.guild_standing import ActorContext, InstallContext
from app.db import cohorts
from app.db.initiative_rls import entity_tables, governing_path
from app.db.session import (
    SYSTEM_SATISFIED,
    SystemSessionLocal,
    routed_guild_id,
    set_rls_context,
)
from app.models.platform.guild import (
    GUILD_ADMIN_ROLES,
    GuildMembership,
)
from app.models.platform.notification import Notification, NotificationType
from app.models.platform.user import User
from app.models.platform.user_notification_prefs import (
    EmailCadence,
    UserNotificationPrefs,
)
from app.models.tenant._mixins import tool_models
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
    RSVPStatus,
)
from app.models.tenant.event_reminder_dispatch import EventReminderDispatch
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.reaction_digest import ReactionDigestItem
from app.models.tenant.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.services import email as email_service
from app.services import permissions as permissions_service
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.services.guild_sweeps import Scan, Scope
from app.services.platform import accounts as accounts_service
from app.services.platform import (
    email_outbox,
    notification_policy,
    notification_prefs,
    push_notifications,
    user_notifications,
)
from app.core.user_input_validators import resolve_zone

logger = logging.getLogger(__name__)


# ── who acted, what it is about, and one way to tell people ──────────────────


@dataclass(frozen=True)
class AppAuthor:
    """An installed app, as a notification names what it did.

    By its name in the community, and by no account: ``id`` is ``None``, so a
    recipient is never mistaken for the one who acted, and the ``*_id`` a
    notification records beside the name is empty.
    """

    name: str
    id: None = None


def actor_name(actor: "User | AppAuthor") -> str:
    """What a notification calls whoever caused it: a person's handle, or an
    installed app's name."""
    if isinstance(actor, AppAuthor):
        return actor.name
    return handle_of(actor)


async def author_of(
    session: AsyncSession, actor: ActorContext, user: User | None
) -> "User | AppAuthor":
    """Who a request's notifications say acted: the person, or — for an
    installed app — the install's name in its community, read from its own
    row on the request's session."""
    if user is not None:
        return user
    if not isinstance(actor, InstallContext):
        raise RuntimeError("a request with no person is an installed app's")
    name = (
        await session.exec(select(GuildApp.name).where(GuildApp.id == actor.install_id))
    ).scalar_one()
    return AppAuthor(name=name)


# My Tasks is the app root: the cross-guild list of everything assigned to you.
# Cross-guild notifications point here instead of at one guild's copy.
MY_TASKS_TARGET_PATH = "/"


@dataclass(frozen=True)
class Channels:
    """Which ways this notification may reach one recipient.

    ``in_app`` is applied by ``user_notifications.create_notification`` — the
    single place every notification is written — so notifiers read it only when
    they need to know whether a line exists. Email and push are the caller's to
    apply, because only the caller knows what it would say.
    """

    in_app: bool
    email: bool
    push: bool
    #: The document the three answers above came from. Every notifier needs it
    #: twice — once to pick channels, once to decide when the email may go —
    #: so resolving it here saves loading the same row again.
    prefs: Mapping[str, Any]


async def _channels(
    session: AsyncSession,
    recipient: User,
    *,
    notification_type: NotificationType,
    guild_id: int | None = None,
    prefs: Mapping[str, Any] | None = None,
) -> Channels:
    """How this recipient wants to hear about this, on each channel.

    ``prefs`` lets a caller fanning out to an audience resolve the whole set
    from one batch load rather than a query per recipient.
    """
    if prefs is None:
        prefs = await notification_prefs.load_prefs_for_delivery(recipient.id)
    # Holds are folded in here rather than left to each caller to remember,
    # through the one resolver the other two fan-out paths also use. Email is
    # the exception it makes for itself: a held email is deferred rather than
    # refused, so this asks only whether the account wants it and lets
    # ``email_due_at`` decide when it goes.
    allowed = {
        channel: notification_prefs.reachable(
            prefs,
            notification_type=notification_type,
            channel=channel,
            guild_id=guild_id,
            tz_name=recipient.timezone,
            last_active_at=recipient.last_active_at,
        )
        for channel in (Channel.in_app, Channel.push)
    }
    allowed[Channel.email] = notification_prefs.wants(
        prefs,
        notification_type=notification_type,
        channel=Channel.email,
        guild_id=guild_id,
    )
    return Channels(
        in_app=allowed[Channel.in_app],
        email=allowed[Channel.email],
        push=allowed[Channel.push],
        prefs=prefs,
    )


#: A thing a notice names: a kind from ``initiative_rls.entity_tables`` and its
#: id — ``("task", 7)``, ``("calendar_event", 3)``, ``("wiki_page", 12)``.
Ref = tuple[str, int]

#: The kinds the client opens by their own address (``/go/{kind}/{id}``) —
#: every commentable kind, and a calendar event. Mirrors the client resolver in
#: ``lib/entityResolver.ts``. Any other kind opens the tool that governs it.
_ADDRESSABLE = frozenset((*COMMENT_TARGETS, "calendar_event"))

#: ``recipients`` for news about a thing nobody asked for — it was shared with
#: you: everybody its sharing reaches, taken from the thing itself.
SHARED_WITH = "shared_with"


@dataclass(frozen=True)
class Subject:
    """What a notice is about, resolved through the registries the policies
    are rendered from: the tool row whose sharing governs it, who that sharing
    reaches, and where the notice opens."""

    tool: Tool
    initiative_id: int | None
    #: The row of ``tool`` that governs it: the project a task is in.
    resource_id: int
    #: Who the thing is shared with, against the roster as it stands.
    shared_with: frozenset[int]
    #: Everybody who can open it now: ``shared_with`` and the community's
    #: admins, who reach everything in it.
    readers: frozenset[int]
    target_path: str


def _place_of(about: Ref, subject: Subject) -> dict[str, Any]:
    """Where a line about ``about`` sits, all the way down: its initiative, its
    tool and that tool's row, and the thing itself."""
    return {
        "initiative_id": subject.initiative_id,
        "tool": subject.tool.value,
        "resource_id": subject.resource_id,
        "subject_type": about[0],
        "subject_id": about[1],
    }


async def resolve_subject(session: AsyncSession, ref: Ref) -> Subject | None:
    """Resolve ``ref`` on the caller's routed session, or ``None`` when the
    session cannot reach it.

    The governing tool and the hops to it come from ``governing_path`` — a task
    reaches its project by ``project_id``, an event its calendar by
    ``calendar_id`` — so no notifier names its tool. Who it is shared with is
    the schema's ``resource_audience`` (``permissions.audience``), the rule the
    post audience uses.
    """
    kind, entity_id = ref
    table = entity_tables()[kind]
    walk = governing_path(table)
    if walk is None:
        raise ValueError(f"no tool governs {kind!r}")
    tool, hops = walk
    row_id: int | None = entity_id
    for column, parent in hops:
        step = sa_table(table, sa_column("id"), sa_column(column))
        row_id = (
            await session.exec(select(step.c[column]).where(step.c.id == row_id))
        ).scalar_one_or_none()
        if row_id is None:
            return None
        table = parent
    model = tool_models()[tool.plural]
    row = (
        await session.exec(select(model).where(model.id == row_id))
    ).scalar_one_or_none()
    if row is None:
        return None
    members = (
        await session.exec(
            select(GuildMembership.user_id, GuildMembership.role).where(
                GuildMembership.guild_id == routed_guild_id(session)
            )
        )
    ).all()
    admins = {user_id for user_id, role in members if role in GUILD_ADMIN_ROLES}
    shared = (await permissions_service.audience(session, tool, [row.id])).get(
        row.id, set()
    )
    return Subject(
        tool=tool,
        initiative_id=row.initiative_id,
        resource_id=row.id,
        shared_with=frozenset(shared),
        readers=frozenset(shared | admins),
        target_path=(
            reference_path(kind, entity_id)
            if kind in _ADDRESSABLE
            else reference_path(tool, row.id)
        ),
    )


async def notify(
    session: AsyncSession,
    notification_type: NotificationType,
    recipients: Iterable[int | None] | str,
    *,
    about: Ref | None,
    key: str,
    values: Mapping[str, str | Callable[[User], str]] | None = None,
    data: Mapping[str, Any] | None = None,
    actor: "User | AppAuthor | None" = None,
    rollup_key: str | None = None,
    email: Callable[[User], email_service.EmailPieces] | None = None,
    email_names_line: bool = True,
) -> None:
    """Tell ``recipients`` one thing: a bell line each, then email and push.

    Every notice in the app goes through here, and it never commits — the
    caller's transaction is what it rides on.

    ``about`` is what the notice names. It decides who may hear it (only people
    who can open it), where it opens and where it sits in the navigation;
    ``None`` is news about the community itself, which every recipient already
    belongs to. The community is the session's routing.

    ``key`` is the prefix the email (``email`` namespace: ``subject``, ``title``,
    ``body``) and the push (``notifications``: ``title``, ``body``) share, filled
    from ``values``; a callable value is asked per recipient. ``email`` builds
    the letter instead, for the notices whose mail is written elsewhere.

    With a ``rollup_key`` the notice joins the recipient's unread line for that
    thread, naming ``actor``, and email and push go only when it opened a new
    one. ``email_names_line=False`` leaves the mail standing when the line is
    read — for a notice waiting on somebody's decision.
    """
    guild_id = routed_guild_id(session)
    payload: dict[str, Any] = {**(data or {}), "guild_id": guild_id}
    allowed: frozenset[int] = frozenset()
    if about is not None:
        subject = await resolve_subject(session, about)
        if subject is None:
            return
        allowed = subject.readers
        if recipients == SHARED_WITH:
            recipients = sorted(subject.shared_with)
        payload.update(_place_of(about, subject))
        payload.setdefault("target_path", subject.target_path)
    elif recipients == SHARED_WITH:
        raise ValueError("SHARED_WITH needs something to be shared")
    payload.setdefault("target_path", "/")
    payload["smart_link"] = _build_smart_link(
        target_path=payload["target_path"], guild_id=guild_id
    )
    wanted: list[int] = []
    for user_id in cast(Iterable[int | None], recipients):
        if (
            user_id is not None
            and user_id != actor_id(actor)
            and (about is None or user_id in allowed)
            and user_id not in wanted
        ):
            wanted.append(user_id)
    if not wanted:
        return
    # On the system engine: an account's settings and address are not a
    # guild's to read. Anybody who ignores the actor drops out here.
    accounts = await accounts_service.load(
        wanted, excluding_ignorers_of=actor_id(actor)
    )
    all_prefs = await notification_prefs.load_prefs_for_delivery_many(list(accounts))
    push_ids = {
        name: str(value)
        for name, value in payload.items()
        if name.endswith("_id") and name != "guild_id" and value is not None
    }
    for user_id in wanted:
        recipient = accounts.get(user_id)
        if recipient is None:
            continue
        channels = await _channels(
            session,
            recipient,
            notification_type=notification_type,
            guild_id=guild_id,
            prefs=all_prefs.get(user_id, {}),
        )
        if rollup_key is None:
            opened = True
            line = await user_notifications.create_notification(
                session,
                user_id=user_id,
                notification_type=notification_type,
                data=payload,
                prefs=channels.prefs,
            )
        else:
            if actor is None:
                raise ValueError("a rolled-up notice names who acted")
            opened, line = await _roll_up_comment(
                session,
                recipient=recipient,
                notification_type=notification_type,
                rollup_key=rollup_key,
                data=payload,
                commenter_name=actor_name(actor),
                commenter_id=actor.id,
                prefs=channels.prefs,
            )
        if not opened:
            continue
        locale = _recipient_locale(recipient)
        filled = {
            name: value if isinstance(value, str) else value(recipient)
            for name, value in (values or {}).items()
        }
        if channels.email:
            pieces = (
                email(recipient)
                if email is not None
                else email_service.EmailPieces(
                    subject=email_t(f"{key}.subject", locale, escape=False, **filled),
                    headline=email_t(f"{key}.title", locale, **filled),
                    body=email_t(f"{key}.body", locale, **filled),
                )
            )
            if pieces.link is None:
                pieces = replace(pieces, link=payload["smart_link"])
            await email_outbox.enqueue(
                session,
                recipient,
                category=category_of(notification_type),
                guild_id=guild_id,
                notification_id=(
                    line.id if line is not None and email_names_line else None
                ),
                prefs=channels.prefs,
                pieces=pieces,
            )
        if channels.push:
            try:
                await push_notifications.send_push_to_user(
                    session=session,
                    user_id=user_id,
                    notification_type=notification_type,
                    guild_id=guild_id,
                    locale=locale,
                    title=_nt(f"{key}.title", locale, **filled),
                    body=_nt(f"{key}.body", locale, **filled),
                    data={
                        "type": notification_type.value,
                        **push_ids,
                        "guild_id": str(guild_id),
                        "target_path": payload["target_path"],
                    },
                )
            except Exception as exc:
                logger.error("Failed to send push notification: %s", exc, exc_info=True)


def actor_id(actor: "User | AppAuthor | None") -> int | None:
    """The account behind whoever acted, or ``None`` for an installed app."""
    return actor.id if actor is not None else None


def event_when(event: CalendarEvent, recipient: User) -> str:
    """An event's start as its reader reads it: the date for an all-day event,
    otherwise the time in their own zone (``Wed, Jul 1, 2026 at 2:30 PM PDT``)."""
    if event.all_day:
        return event.start_at.strftime("%a, %b %-d, %Y")
    local = event.start_at.astimezone(resolve_zone(recipient.timezone))
    return local.strftime("%a, %b %-d, %Y at %-I:%M %p %Z")


def _normalize_target_path(target_path: str) -> str:
    if not target_path:
        return "/"
    return target_path if target_path.startswith("/") else f"/{target_path}"


def _build_smart_link(*, target_path: str, guild_id: int | None) -> str | None:
    if guild_id is None:
        return None
    normalized = _normalize_target_path(target_path)
    encoded = quote(normalized, safe="")
    base = app_config.APP_URL.rstrip("/") or "http://localhost:5173"
    return f"{base}/navigate?guild_id={guild_id}&target={encoded}"


# A tool entity's URL names its initiative (/i/{initiative}/projects/{id}), and
# a notifier holds only the entity id — reaching the initiative here would mean
# an extra load at every call site, and a stored target_path would go stale the
# moment an entity moved. So these emit an entity REFERENCE and let the client's
# /go resolver turn it into the canonical address on the way in.
def reference_path(kind: Tool | str, entity_id: int | None) -> str:
    """One entity's reference path, the same for every notifier and for any
    other service that addresses the entity.

    ``kind`` is a ``Tool``, or the name of a kind that lives inside one
    (``task``, ``event``), spelled the way the client's resolver speaks it —
    kebab singular. Without an id there is no entity to resolve, so the guild
    home is the landing spot.
    """
    if entity_id is None:
        return "/"
    name = kind.value if isinstance(kind, Tool) else kind
    return f"/go/{name.replace('_', '-')}/{entity_id}"


def _task_target_path(task_id: int | None, project_id: int | None) -> str:
    """Where a notice about a task opens — the task, or the project holding it
    when the notice names no one task."""
    if task_id:
        return reference_path("task", task_id)
    if project_id:
        return reference_path(Tool.project, project_id)
    # No entity to resolve — the guild home is the only honest landing spot now
    # that there is no guild-wide project list.
    return "/"


def _initiative_target_path(initiative_id: int | None) -> str:
    """An initiative is addressed directly rather than through the resolver: it
    is the thing tool references resolve INTO, so it has a stable address of its
    own."""
    if initiative_id is None:
        # No one initiative to open, so land on the guild's front page — which
        # is where the initiative list lives now that the standalone page is
        # gone. "/i" would only redirect here anyway.
        return "/"
    return f"/i/{initiative_id}"


def _recipient_locale(user: User) -> str:
    return getattr(user, "locale", None) or "en"


def _nt(key: str, locale: str, **kwargs: str | int) -> str:
    """Translate a push string from the ``notifications`` namespace.

    Push notifications carry only a ``title`` and ``body``. Email copy for the
    same events lives in the ``email`` namespace (``email_t``); the two are kept
    separate because their wording differs (push is terse, email is richer).
    """
    return translate(key, locale, namespace="notifications", **kwargs)


# ── a flurry of comments is one line ─────────────────────────────────────────

#: How many commenters one rolled-up line remembers by name. ``comment_count``
#: above it stays the whole truth; this only bounds how much the payload
#: carries so a busy thread cannot grow it without limit.
MAX_ROLLED_UP_COMMENTERS = 10


async def _lock_rollup_line(session: AsyncSession, key: str) -> None:
    """Serialize the read-then-write on one recipient's rolled-up line.

    Every rollup in the app does the same thing — look for an unread line to
    join, then write or extend it — so they all take this. Transaction-scoped,
    and keyed narrowly enough that only events aimed at the same line ever wait.
    """
    await session.exec(
        select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0)))
    )


def _same_commenter(
    entry: Mapping[str, Any], commenter_id: int | None, commenter_name: str
) -> bool:
    """Whether a roster entry is this commenter: a person by id, an installed
    app (no id) by its name."""
    if commenter_id is None:
        return entry.get("id") is None and entry.get("name") == commenter_name
    return entry.get("id") == commenter_id


def _rolled_up_comment(
    previous: Mapping[str, Any] | None,
    *,
    commenter_name: str,
    commenter_id: int | None,
) -> dict[str, Any]:
    """Fold one more comment into a line's payload.

    The roster of distinct commenters is what the sentence names, and the count
    is every comment the line stands for. An installed app is on it by name,
    with no id. ``opened_at`` is when the line's first comment arrived and does
    not move as it rolls: every comment since then is one it stands for.
    """
    previous = previous or {}
    # One roster of pairs rather than parallel id and name lists: those have to
    # stay aligned, and nothing keeps them that way once a repeat commenter is
    # moved to the end.
    roster: list[dict[str, Any]] = [
        entry
        for entry in (previous.get("commenters") or [])
        if isinstance(entry, Mapping)
        and (
            isinstance(entry.get("id"), int)
            or (entry.get("id") is None and isinstance(entry.get("name"), str))
        )
    ]
    # Same person again: they move to the end rather than being listed twice,
    # and the comment count still moves.
    roster = [
        entry
        for entry in roster
        if not _same_commenter(entry, commenter_id, commenter_name)
    ]
    roster.append({"id": commenter_id, "name": commenter_name})
    raw_count = previous.get("comment_count")
    count = (raw_count if isinstance(raw_count, int) else 0) + 1
    # ``commenter_count`` is the whole crowd; the roster is only as much of it
    # as the line carries, so a busy thread does not grow the payload without
    # limit. Counting the roster would understate it.
    raw_people = previous.get("commenter_count")
    people = raw_people if isinstance(raw_people, int) else 0
    seen_before = any(
        _same_commenter(entry, commenter_id, commenter_name)
        for entry in (previous.get("commenters") or [])
        if isinstance(entry, Mapping)
    )
    return {
        "opened_at": previous.get("opened_at")
        or datetime.now(timezone.utc).isoformat(),
        "comment_count": count,
        "commenters": roster[-MAX_ROLLED_UP_COMMENTERS:],
        "commenter_count": people if seen_before else people + 1,
    }


async def _roll_up_comment(
    session: AsyncSession,
    *,
    recipient: User,
    notification_type: NotificationType,
    rollup_key: str,
    data: dict[str, Any],
    commenter_name: str,
    commenter_id: int | None,
    prefs: Mapping[str, Any] | None = None,
) -> tuple[bool, Notification | None]:
    """Write or extend the one unread line for this thread.

    Returns whether this comment opened a new window — which is when the
    reaching channels fire — and the line it wrote, so the email can ride on it
    and be withdrawn if the thread is read before the mail goes out. A second comment updates the line instead and sends
    nothing: the flurry is one interruption, not twenty. Once the line has been
    read, the next comment starts a fresh one and they fire again.

    The unread line IS the window, so an account that has switched the bell off
    for this category has no window to roll into and hears about each comment
    on whichever reaching channel it left on. That is the honest reading of
    "no bell, but do email me": there is nothing to collect them into.
    """
    match = {"rollup_key": rollup_key}
    # Two comments landing on the same thread at once would otherwise both find
    # no line to join and write one each, or both read the same count and lose
    # one. Transaction-scoped and keyed per (recipient, thread), so only
    # comments aimed at the same line ever wait — the same lock the reaction
    # and direct-message rollups take.
    await _lock_rollup_line(session, f"comment-line:{rollup_key}:{recipient.id}")
    existing = await user_notifications.find_unread_by_data(
        session,
        user_id=recipient.id,
        notification_type=notification_type,
        match=match,
    )
    rolled = _rolled_up_comment(
        existing.data if existing else None,
        commenter_name=commenter_name,
        commenter_id=commenter_id,
    )
    line = {**data, "rollup_key": rollup_key, **rolled}
    if existing is None:
        written = await user_notifications.create_notification(
            session,
            user_id=recipient.id,
            notification_type=notification_type,
            data=line,
            prefs=prefs,
        )
        return True, written
    await user_notifications.refresh_notification(session, existing, data=line)
    return False, None


# ── digests: the task-assignment digest and the machinery ────────────────────

# A task-assignment digest waits for the flurry to end rather than firing on
# the first item: it ships once nothing new has arrived for QUIET_PERIOD, so a
# lone assignment still lands promptly while a burst collapses into one
# notification. MAX_WINDOW bounds how long a steady trickle can hold it back.
ASSIGNMENT_QUIET_PERIOD = timedelta(minutes=5)


ASSIGNMENT_MAX_WINDOW = timedelta(minutes=30)


# How long a sent digest's items are kept before the GC sweep drops them. They
# are only bookkeeping once delivered; the notification itself lives in the
# bell. Unsent items are dropped at the same age — anything that old is either
# orphaned or long past being worth sending.
ASSIGNMENT_ITEM_RETENTION = timedelta(days=7)


async def notify_assigned(
    session: AsyncSession,
    task: Task,
    assignee_ids: Iterable[int | None],
    *,
    assigned_by: "User | AppAuthor",
    project_name: str,
) -> None:
    """Tell the people just assigned to ``task``, among those who can open it.

    The bell line is written at once; email and push wait for the assignment
    digest, which is queued when either channel is on for the community and
    re-reads both when it sends. The caller commits.
    """
    about: Ref = ("task", cast(int, task.id))
    subject = await resolve_subject(session, about)
    if subject is None:
        return
    guild_id = routed_guild_id(session)
    wanted = [
        user_id
        for user_id in dict.fromkeys(assignee_ids)
        if user_id is not None
        and user_id != assigned_by.id
        and user_id in subject.readers
    ]
    if not wanted:
        return
    accounts = await accounts_service.load(wanted, excluding_ignorers_of=assigned_by.id)
    all_prefs = await notification_prefs.load_prefs_for_delivery_many(list(accounts))
    smart_link = _build_smart_link(target_path=subject.target_path, guild_id=guild_id)
    for user_id in accounts:
        prefs = all_prefs.get(user_id, {})
        await user_notifications.create_notification(
            session,
            user_id=user_id,
            notification_type=NotificationType.task_assignment,
            data={
                "task_id": task.id,
                "project_id": task.project_id,
                "assigned_by_name": actor_name(assigned_by),
                "guild_id": guild_id,
                **_place_of(about, subject),
                "target_path": subject.target_path,
                "smart_link": smart_link,
            },
            prefs=prefs,
        )
        if wants_assignment_digest(prefs, guild_id=guild_id):
            session.add(
                TaskAssignmentDigestItem(
                    user_id=user_id,
                    task_id=task.id,
                    project_id=task.project_id,
                    task_title=task.title,
                    project_name=project_name,
                    assigned_by_name=actor_name(assigned_by),
                    assigned_by_id=assigned_by.id,
                )
            )


def wants_assignment_digest(
    prefs: Mapping[str, Any] | None, *, guild_id: int | None = None
) -> bool:
    """Whether a user still wants the assignment digest on either channel."""
    return wants_digest(prefs, NotificationCategory.assignments, guild_id=guild_id)


async def dequeue_task_assignment_events(
    session: AsyncSession, *, task_id: int, user_ids: list[int]
) -> None:
    """Drop pending digest items for users just unassigned from ``task_id``.

    A digest that has not gone out yet should not announce an assignment that
    no longer holds. Operates on the CURRENTLY ROUTED guild schema, which is
    the task's own. Already-sent items are left alone — that mail is gone.
    """
    if not user_ids:
        return
    await session.exec(
        delete(TaskAssignmentDigestItem).where(
            TaskAssignmentDigestItem.task_id == task_id,
            TaskAssignmentDigestItem.user_id.in_(tuple(user_ids)),
            TaskAssignmentDigestItem.processed_at.is_(None),
        )
    )


async def clear_digest_queue_for_user(
    session: AsyncSession, user_id: int, models: Sequence[type]
) -> None:
    """Clear the user's pending items in the CURRENTLY ROUTED guild schema.
    Callers on the platform path (no guild route) must use
    :func:`clear_digest_queue_across_guilds` instead."""
    for model in models:
        await session.exec(
            delete(model).where(
                model.user_id == user_id,
                model.processed_at.is_(None),
            )
        )


async def clear_digest_queue_across_guilds(
    session: AsyncSession, user_id: int, models: Sequence[type]
) -> None:
    """Platform-path variant: a digest queue is guild-scoped, so visit each
    of the user's guild schemas. When each community is visited on a session
    of its own (``gather_across_guilds`` with cohorts), each one's deletes are
    committed there; otherwise they are flushed on ``session``, which is left
    routed into the last guild with its identity map expunged, and ride the
    caller's transaction. Either way the caller restores its own context."""
    from app.services import cross_guild

    guild_ids = await cross_guild.member_guild_ids(session, user_id)

    async def _clear(routed: AsyncSession, _gid: int) -> list:
        await clear_digest_queue_for_user(routed, user_id, models)
        return []

    # Membership-based hygiene, not content access: must reach every guild
    # the user belongs to, including auth-policy-gated ones.
    await cross_guild.gather_across_guilds(
        session,
        user_id,
        guild_ids,
        _clear,
        satisfied_providers=SYSTEM_SATISFIED,
        writes=True,
    )


async def _send_assignment_push(
    session: AsyncSession, user: User, assignments: list[dict]
) -> tuple[bool, bool]:
    """Push a task-assignment digest. Returns ``(delivered, retry_worth_it)``.

    A digest of one names its task and deep-links to it; a larger one spans
    guilds, so it points at My Tasks the way the overdue digest does.
    """
    locale = _recipient_locale(user)
    first = assignments[0]
    if any(item.get("redacted") for item in assignments):
        title, body = notification_policy.redacted_push(
            NotificationType.task_assignment, locale
        )
    else:
        title = _nt("task.assignment.title", locale)
        body = _nt(
            "task.assignment.body",
            locale,
            count=len(assignments),
            title=first.get("task_title") or "",
            project=first.get("project_name") or "",
        )
    data: dict[str, str] = {
        "type": NotificationType.task_assignment.value,
        "count": str(len(assignments)),
        "target_path": MY_TASKS_TARGET_PATH,
    }
    if len(assignments) == 1 and first.get("guild_id") is not None:
        data["target_path"] = _task_target_path(
            first.get("task_id"), first.get("project_id")
        )
        data["guild_id"] = str(first["guild_id"])
    try:
        sent = await push_notifications.send_push_to_user(
            session=session,
            user_id=user.id,
            notification_type=NotificationType.task_assignment,
            locale=locale,
            title=title,
            body=body,
            data=data,
        )
    except Exception as exc:
        logger.error("Failed to send assignment digest push: %s", exc, exc_info=True)
        return False, True
    return sent > 0, False


def _digest_is_due(
    timestamps: list[datetime],
    *,
    now: datetime,
    quiet_period: timedelta = ASSIGNMENT_QUIET_PERIOD,
    max_window: timedelta = ASSIGNMENT_MAX_WINDOW,
) -> bool:
    """Whether a user's queued items have settled enough to send.

    The digest ships once nothing new has arrived for ``quiet_period`` — so a
    lone item goes out promptly and a burst arrives as one — or once the oldest
    item hits ``max_window``, which stops a steady trickle from deferring it
    indefinitely.
    """
    if not timestamps:
        return False
    return now - max(timestamps) >= quiet_period or now - min(timestamps) >= max_window


@dataclass(frozen=True)
class DigestSpec:
    """One digested notification stream, described once.

    Every digest in the app works the same way — queue a row per (recipient,
    event) in the guild the event happened in, wait for the flurry to settle,
    then send email and push together off one drain and mark the batch
    processed. What differs between two of them is only what is stated here, so
    the machinery below is written once and a new digest is a spec, not a copy.
    """

    #: Log label ("task-digest", "reaction-digest").
    name: str
    #: The guild-scoped queue table.
    model: type
    #: The category gating both channels. One queue backs them, so the spec
    #: names the thing being digested rather than two column names.
    category: NotificationCategory
    #: What one queued row looks like to the senders, given the guild schema it
    #: was found in (which IS the row's guild).
    row: Callable[[object, int], dict]
    #: The batch as an email, for the outbox to time and send. Pieces rather
    #: than a message: under a digest cadence this becomes one section of a
    #: larger one.
    pieces: Callable[[User, list[dict]], email_service.EmailPieces]
    #: Send the batch as a push. Returns ``(delivered, retry_worth_it)``.
    send_push: Callable[[AsyncSession, User, list[dict]], Awaitable[tuple[bool, bool]]]
    #: ``User`` column recording when the last one went out, if any. A record,
    #: never a gate — the send window comes from the queue itself.
    stamp: str | None = None
    quiet_period: timedelta = ASSIGNMENT_QUIET_PERIOD
    max_window: timedelta = ASSIGNMENT_MAX_WINDOW


def wants_digest(
    prefs: Mapping[str, Any] | None,
    category: NotificationCategory,
    *,
    guild_id: int | None = None,
) -> bool:
    """Whether a user still wants a digest on either reaching channel.

    One queue backs both, so it may only be discarded once neither is on —
    clearing it because the email was switched off would silently take the
    push with it.
    """
    sample = sample_type(category)
    return any(
        notification_prefs.wants(
            prefs, notification_type=sample, channel=channel, guild_id=guild_id
        )
        for channel in (Channel.email, Channel.push)
    )


async def _digest_batch(
    session: AsyncSession, batch: list[dict]
) -> tuple[list[dict], list[dict]]:
    """The items of a digest each channel may still carry, per community.

    A digest gathers from every community an account is in, so what may leave
    with it is answered one community at a time: items from one that declines a
    channel are left out of it, and items from one asking for redacted
    notifications are marked, so the composer writes the kind of thing that
    happened rather than what it was about.

    Returns ``(for_email, for_push)`` — the same items, filtered and marked for
    each channel.
    """
    policies = await notification_policy.for_send_many(
        session, {item.get("guild_id") for item in batch}
    )

    def prepared(item: dict, channel: str) -> dict | None:
        policy = policies[item.get("guild_id")]
        if not getattr(policy, channel):
            return None
        return {**item, "redacted": True} if policy.redact else item

    return (
        [row for item in batch if (row := prepared(item, "email")) is not None],
        [row for item in batch if (row := prepared(item, "push")) is not None],
    )


def digest_scan(spec: DigestSpec, *, now: datetime) -> Scan:
    """Send ``spec``'s digest to opted-in users as of ``now``.

    Starts from what is waiting: each live community is asked once which
    accounts have unsent items and when they came, and only accounts whose
    items have settled go further (see :func:`_digest_is_due`). Their items are
    then taken in each community under their own membership context — marked
    processed by the statement that reads them, so a digest goes out once
    however many processes sweep at the same moment — and email and push ship
    together, so the two channels tell the same story.
    """
    model = spec.model
    pending: dict[int, dict[int, list[datetime]]] = {}

    async def _waiting(routed: AsyncSession, guild_id: int) -> None:
        rows = await routed.exec(
            select(
                model.user_id, func.min(model.created_at), func.max(model.created_at)
            )
            .where(model.processed_at.is_(None))
            .group_by(model.user_id)
        )
        for user_id, first, last in rows.all():
            pending.setdefault(user_id, {})[guild_id] = [first, last]

    async def _finish() -> None:
        if not pending:
            return
        async with cohorts.system_session(None) as session:
            await set_rls_context(session)
            await _send_digests(session, spec, pending, now=now)

    return Scan(Scope.LIVE, _waiting, _finish)


async def _send_digests(
    session: AsyncSession,
    spec: DigestSpec,
    pending: dict[int, dict[int, list[datetime]]],
    *,
    now: datetime,
) -> None:
    """Send the digests of the accounts ``pending`` names, whose items have
    settled."""
    model = spec.model
    # Settings are sparse and default to on, so the opted-in set is "everyone
    # who has not said otherwise". Filtered here rather than in the SELECT: the
    # resolution order lives in one function, and re-expressing it as a JSON
    # predicate would be a second copy of it that could drift. The channel
    # preferences are read again at delivery time.
    all_prefs = await notification_prefs.load_prefs_for(session, list(pending))
    for user_id, held in pending.items():
        if not wants_digest(all_prefs.get(user_id), spec.category):
            continue
        if not _digest_is_due(
            [stamp for pair in held.values() for stamp in pair],
            now=now,
            quiet_period=spec.quiet_period,
            max_window=spec.max_window,
        ):
            continue
        taken: dict[int, list[int]] = {}

        # Defaults bind the loop variables now rather than by reference (B023).
        async def _take(
            routed: AsyncSession, gid: int, *, _uid=user_id, _taken=taken
        ) -> list[dict]:
            # A community set to say less is filtered here, where the guild is
            # known — a digest spans guilds, so this cannot be decided once for
            # the whole batch.
            if not wants_digest(all_prefs.get(_uid), spec.category, guild_id=gid):
                return []
            items = sorted(
                (
                    await routed.exec(
                        sa_update(model)
                        .where(model.user_id == _uid, model.processed_at.is_(None))
                        .values(processed_at=now)
                        .returning(model)
                    )
                ).scalars(),
                key=lambda item: item.created_at,
            )
            _taken[gid] = [item.id for item in items]
            return [spec.row(item, gid) for item in items]

        # Only the communities holding something for them, and only while they
        # still belong to it. Digests act on membership (no live session exists
        # here) — the system sentinel clears the guild auth-policy gate.
        batch = await gather_across_guilds(
            session,
            user_id,
            await member_guild_ids(session, user_id, restrict_to=list(held)),
            _take,
            satisfied_providers=SYSTEM_SATISFIED,
            writes=True,
        )
        if not batch:
            continue
        # Send: re-load the user (gather expunged it) in a shared-table context.
        session.expunge_all()
        await set_rls_context(session, user_id=user_id)
        user = (
            await session.exec(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:  # deleted since the scan — skip, don't abort the pass
            continue
        delivered = False
        # A channel that is merely unconfigured will never deliver these items,
        # so holding the queue for it would re-send nothing every poll forever.
        # Only a transient failure is worth another pass.
        retry = False
        # Re-read the preferences off the row just reloaded, not the snapshot
        # taken before the cross-guild gather: a channel switched off while the
        # gather was running must not still be delivered to.
        channels = await _channels(
            session, user, notification_type=sample_type(spec.category)
        )
        email_batch, push_batch = await _digest_batch(session, batch)
        if channels.email and email_batch:
            # No community: a digest gathers from every guild the account is
            # in, so there is no one of them it happened in. Each item carries
            # its own community's answer instead.
            delivered = await email_outbox.enqueue(
                session,
                user,
                category=spec.category,
                prefs=channels.prefs,
                pieces=spec.pieces(user, email_batch),
            )
            if not delivered:
                logger.warning(
                    "SMTP not configured; holding %s for %s", spec.name, user_id
                )
        if channels.push and push_batch:
            pushed, push_retry = await spec.send_push(session, user, push_batch)
            delivered = delivered or pushed
            retry = retry or push_retry
        if retry and not delivered:
            # Nothing went out and a later pass could still deliver them: the
            # items go back to waiting, in each community they were taken from.
            for gid, item_ids in taken.items():
                async with cohorts.system_session(gid) as routed:
                    await set_rls_context(routed, guild_id=gid)
                    await routed.exec(
                        sa_update(model)
                        .where(model.id.in_(item_ids), model.processed_at == now)
                        .values(processed_at=None)
                    )
                    await routed.commit()
            continue
        if retry:  # pragma: no cover — one channel got through, the other did not
            # The two channels share one queue with a single processed marker,
            # so the batch is consumed either way. Consuming loses one channel's
            # copy; retaining would re-send the channel that already succeeded,
            # and a duplicate digest is the louder failure. Logged so the loss
            # is visible rather than silent.
            logger.warning(
                "%s: a channel failed after another delivered; "
                "%d item(s) not retried for user %s",
                spec.name,
                len(batch),
                user_id,
            )
        if spec.stamp is not None:
            setattr(user, spec.stamp, now)
            session.add(user)
        await session.commit()


def digest_gc_scan(*, now: datetime) -> Scan:
    """Drop digest items older than the retention window, community by
    community, then the settled mail and the read notifications past theirs.

    Sent items are bookkeeping once the mail is gone. Unsent items of the same
    age are dropped too: they are either orphaned (the user turned the channel
    off in a guild an admin could not reach) or so stale that announcing them
    would be noise.
    """
    cutoff = now - ASSIGNMENT_ITEM_RETENTION

    async def _visit(routed: AsyncSession, _guild_id: int) -> None:
        for model in (TaskAssignmentDigestItem, ReactionDigestItem):
            await routed.exec(delete(model).where(model.created_at < cutoff))

    async def _finish() -> None:
        async with cohorts.system_session(None) as session:
            await set_rls_context(session)
            # Mail that has gone out, or run out of attempts, is bookkeeping on
            # the same terms as a spent digest row.
            dropped = await email_outbox.sweep_settled(session, now=now)
            if dropped:
                logger.info("digest-gc: dropped %d settled email row(s)", dropped)
            await session.commit()
            # Read notifications past their retention go on the same sweep.
            pruned = await user_notifications.prune_read(session, now=now)
            if pruned:
                logger.info("digest-gc: deleted %d read notification(s)", pruned)

    return Scan(Scope.LIVE, _visit, _finish)


def _assignment_row(item, guild_id: int) -> dict:
    return {
        "task_title": item.task_title,
        "project_name": item.project_name,
        "assigned_by_name": item.assigned_by_name,
        "link": _build_smart_link(
            target_path=_task_target_path(item.task_id, item.project_id),
            guild_id=guild_id,  # the item's guild IS the routed schema
        ),
        # The push carries one deep link rather than a list; these let a digest
        # of one point at its task. Ignored by the email, which renders
        # ``link`` per row.
        "task_id": item.task_id,
        "project_id": item.project_id,
        "guild_id": guild_id,
    }


ASSIGNMENT_DIGEST = DigestSpec(
    name="task-digest",
    model=TaskAssignmentDigestItem,
    category=NotificationCategory.assignments,
    row=_assignment_row,
    pieces=email_service.task_assignment_digest_pieces,
    send_push=_send_assignment_push,
    stamp="last_task_assignment_digest_at",
)


# ── reactions ────────────────────────────────────────────────────────────────

#: How many individual reactions one rolled-up bell line remembers in detail.
#: ``count`` above it stays the whole truth; this only bounds how much of the
#: payload the line carries so a popular comment cannot grow it without limit.
MAX_ROLLED_UP_REACTIONS = 20


# The roster of distinct reactors is deliberately NOT capped. It is what the
# sentence counts ("and 12 others"), so a bound on it is a bound on the truth:
# capping it would freeze the count and understate the crowd on exactly the
# comment where the number matters most. Unlike the detail above it costs one
# integer per person, it can only grow to the number of people who can see the
# comment, and the whole line goes the moment the recipient reads it.


def _reaction_rollup_match(reaction, guild_id: int) -> dict[str, object]:
    """What makes two reactions the same bell line: same guild, same thing
    reacted to. Emoji and reactor deliberately do not — they are what the one
    line rolls up."""
    return {
        "guild_id": guild_id,
        "target_type": reaction.target_type,
        "target_id": reaction.target_id,
    }


def _rolled_up_reactions(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The individual reactions a bell line is already carrying."""
    rolled = data.get("reactions")
    if isinstance(rolled, list):
        return [entry for entry in rolled if isinstance(entry, dict)]
    # A line written before the bell rolled these up names its one reaction in
    # the top-level fields instead.
    if data.get("emoji"):
        return [
            {
                "id": None,
                "emoji": data.get("emoji"),
                "reactor_id": data.get("reactor_id"),
                "reactor_name": data.get("reactor_name"),
            }
        ]
    return []


def _rolled_up_reactor_ids(data: Mapping[str, Any]) -> list[int]:
    """The distinct people a bell line has rostered, oldest first.

    A line written before the roster existed answers from the reactions it
    still remembers, which for such a line is all it ever had.
    """
    rostered = data.get("reactor_ids")
    if isinstance(rostered, list):
        return [value for value in rostered if isinstance(value, int)]
    seen: list[int] = []
    for entry in _rolled_up_reactions(data):
        reactor_id = entry.get("reactor_id")
        if isinstance(reactor_id, int) and reactor_id not in seen:
            seen.append(reactor_id)
    return seen


def _rolled_up_count(data: Mapping[str, Any]) -> int:
    """How many reactions the line stands for, including any that have rolled
    past :data:`MAX_ROLLED_UP_REACTIONS`."""
    try:
        count = int(data.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    return count or len(_rolled_up_reactions(data))


#: What a reaction line carries about where it sits, kept as a line rolls and
#: read back when a gesture is withdrawn.
_REACTION_PLACE = (
    "initiative_id",
    "tool",
    "resource_id",
    "subject_type",
    "subject_id",
    "target_path",
    "smart_link",
)


def _reaction_line(
    entries: Sequence[dict[str, Any]],
    *,
    count: int,
    reactor_ids: Sequence[int],
    target_type: str,
    target_id: int,
    guild_id: int,
    place: Mapping[str, Any],
) -> dict[str, Any]:
    """One bell payload for every reaction rolled up so far.

    ``emoji`` / ``reactor_name`` / ``reactor_id`` keep naming the most recent
    one: a client that predates the rollup still renders a true sentence, and
    the newer client uses them as the reactor it names first. ``reactor_ids``
    is what the sentence counts, so it outlives the detail entries — a line
    whose oldest reactions have rolled off still knows how many people are in
    it. ``place`` is where the line sits and opens (:data:`_REACTION_PLACE`).
    """
    latest = entries[-1] if entries else {}
    return {
        "target_type": target_type,
        "target_id": target_id,
        "guild_id": guild_id,
        **{key: place.get(key) for key in _REACTION_PLACE},
        "emoji": latest.get("emoji"),
        "reactor_name": latest.get("reactor_name"),
        "reactor_id": latest.get("reactor_id"),
        "count": count,
        "reactor_count": len(reactor_ids),
        "reactor_ids": list(reactor_ids),
        "reactions": list(entries[-MAX_ROLLED_UP_REACTIONS:]),
    }


async def enqueue_reaction_event(
    session: AsyncSession,
    *,
    author: User,
    reactor: User,
    reaction,
    context_title: str,
    about: Ref,
    subject: Subject,
    guild_id: int,
) -> None:
    """Record that someone reacted to something ``author`` wrote, on the thread
    or post ``about`` names (resolved by the caller as ``subject``).

    Reactions are the lightest signal in the app and they arrive in flurries,
    so every channel digests them — including the bell, which rolls them up per
    thing-reacted-to rather than listing one entry per tap. An unread line
    absorbs the next reaction to the same comment and returns to the top of the
    inbox; once read, the next reaction starts a fresh line. Email and push
    wait for the digest worker as before.
    """
    if author.id == reactor.id:
        return
    target_path = subject.target_path
    place = {
        **_place_of(about, subject),
        "target_path": target_path,
        "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
    }
    reactor_name = handle_of(reactor)
    entry = {
        "id": reaction.id,
        "emoji": reaction.emoji,
        "reactor_id": reactor.id,
        "reactor_name": reactor_name,
    }
    await _lock_rollup_line(
        session,
        f"reaction-bell:{guild_id}:{reaction.target_type}:"
        f"{reaction.target_id}:{author.id}",
    )
    existing = await user_notifications.find_unread_by_data(
        session,
        user_id=author.id,
        notification_type=NotificationType.comment_reaction,
        match=_reaction_rollup_match(reaction, guild_id),
    )
    prefs = await notification_prefs.load_prefs_for_delivery(author.id)
    previous: Mapping[str, Any] = (existing.data if existing else None) or {}
    roster = _rolled_up_reactor_ids(previous)
    if reactor.id not in roster:
        roster.append(cast(int, reactor.id))
    line = _reaction_line(
        _rolled_up_reactions(previous) + [entry],
        count=_rolled_up_count(previous) + 1,
        reactor_ids=roster,
        target_type=reaction.target_type,
        target_id=reaction.target_id,
        guild_id=guild_id,
        place=place,
    )
    if existing is None:
        await user_notifications.create_notification(
            session,
            user_id=author.id,
            notification_type=NotificationType.comment_reaction,
            data=line,
            prefs=prefs,
        )
    else:
        await user_notifications.refresh_notification(session, existing, data=line)
    if wants_digest(prefs, NotificationCategory.reactions, guild_id=guild_id):
        session.add(
            ReactionDigestItem(
                user_id=author.id,
                reaction_id=reaction.id,
                target_type=reaction.target_type,
                target_id=reaction.target_id,
                emoji=reaction.emoji,
                target_path=target_path,
                context_title=context_title,
                reactor_name=reactor_name,
                reactor_id=reactor.id,
            )
        )


def _matches_withdrawn(
    entry: Mapping[str, Any], *, reaction_id: int, reactor_id: int, emoji: str
) -> bool:
    """Whether a rolled-up entry is the gesture being taken back.

    Normally the reaction's own id answers it. A line written before the
    rollup carries no id, so it is matched on who reacted and with what —
    which for a line holding a single gesture is the same question.
    """
    if entry.get("id") == reaction_id:
        return True
    return (
        entry.get("id") is None
        and entry.get("reactor_id") == reactor_id
        and entry.get("emoji") == emoji
    )


async def withdraw_reaction_event(
    session: AsyncSession,
    *,
    author_id: int,
    reaction_id: int,
    reactor_id: int,
    emoji: str,
    target_type: str,
    target_id: int,
    guild_id: int,
) -> None:
    """Take an un-reacted gesture back out of the unread bell line.

    Un-reacting should leave no trace where the recipient has not looked yet,
    the same rule the queued digest line follows. Only a line still holding
    this exact gesture is touched: one the recipient has already read is
    history, and one that has rolled the gesture past the payload cap can no
    longer prove it was ever there, so both are left alone rather than
    decremented on a guess.
    """
    await _lock_rollup_line(
        session,
        f"reaction-bell:{guild_id}:{target_type}:{target_id}:{author_id}",
    )
    existing = await user_notifications.find_unread_by_data(
        session,
        user_id=author_id,
        notification_type=NotificationType.comment_reaction,
        match={
            "guild_id": guild_id,
            "target_type": target_type,
            "target_id": target_id,
        },
    )
    if existing is None:
        return
    previous: Mapping[str, Any] = existing.data or {}
    entries = _rolled_up_reactions(previous)
    remaining = [
        entry
        for entry in entries
        if not _matches_withdrawn(
            entry, reaction_id=reaction_id, reactor_id=reactor_id, emoji=emoji
        )
    ]
    if len(remaining) == len(entries):
        return
    count = _rolled_up_count(previous) - 1
    if count <= 0 or not remaining:
        await user_notifications.delete_notification(session, existing)
        return
    # The reactor leaves the roster only once the line remembers nothing else
    # of theirs — a second emoji of theirs still counts them as present. That
    # question can only be answered off the detail, so it is only asked when
    # the detail is complete: past the cap an older gesture of theirs may have
    # rolled off, and dropping them on its absence would undercount a crowd
    # they are still part of.
    roster = _rolled_up_reactor_ids(previous)
    line_remembers_every_gesture = len(entries) == _rolled_up_count(previous)
    if line_remembers_every_gesture and all(
        entry.get("reactor_id") != reactor_id for entry in remaining
    ):
        roster = [rostered for rostered in roster if rostered != reactor_id]
    await user_notifications.refresh_notification(
        session,
        existing,
        data=_reaction_line(
            remaining,
            count=count,
            reactor_ids=roster,
            target_type=target_type,
            target_id=target_id,
            guild_id=guild_id,
            place={
                **previous,
                "target_path": previous.get("target_path") or MY_TASKS_TARGET_PATH,
            },
        ),
        bump=False,
    )


async def _send_reaction_push(
    session: AsyncSession, user: User, reactions: list[dict]
) -> tuple[bool, bool]:
    """Push a reaction digest. Returns ``(delivered, retry_worth_it)``.

    A digest of one names its emoji and deep-links to what was reacted to; a
    larger one spans guilds, so it points at My Tasks the way the other
    cross-guild digests do.
    """
    locale = _recipient_locale(user)
    first = reactions[0]
    if any(item.get("redacted") for item in reactions):
        title, body = notification_policy.redacted_push(
            NotificationType.comment_reaction, locale
        )
    else:
        title = _nt("comment.reaction.title", locale)
        body = _nt(
            "comment.reaction.body",
            locale,
            count=len(reactions),
            actor=first.get("reactor_name") or "",
            emoji=first.get("emoji") or "",
            context=first.get("context_title") or "",
        )
    data: dict[str, str] = {
        "type": NotificationType.comment_reaction.value,
        "count": str(len(reactions)),
        "target_path": MY_TASKS_TARGET_PATH,
    }
    if len(reactions) == 1 and first.get("guild_id") is not None:
        data["target_path"] = first["target_path"]
        data["guild_id"] = str(first["guild_id"])
    try:
        sent = await push_notifications.send_push_to_user(
            session=session,
            user_id=user.id,
            notification_type=NotificationType.comment_reaction,
            locale=locale,
            title=title,
            body=body,
            data=data,
        )
    except Exception as exc:
        logger.error("Failed to send reaction digest push: %s", exc, exc_info=True)
        return False, True
    return sent > 0, False


def _reaction_row(item, guild_id: int) -> dict:
    return {
        "emoji": item.emoji,
        "reactor_name": item.reactor_name,
        "context_title": item.context_title,
        "target_path": item.target_path,
        "link": _build_smart_link(target_path=item.target_path, guild_id=guild_id),
        "guild_id": guild_id,
    }


REACTION_DIGEST = DigestSpec(
    name="reaction-digest",
    model=ReactionDigestItem,
    category=NotificationCategory.reactions,
    row=_reaction_row,
    pieces=email_service.reaction_digest_pieces,
    send_push=_send_reaction_push,
)


# ── time-driven notices: overdue tasks, hold summaries, reminders ────────────

# A summary goes out when a hold lifts, so the poll only has to be finer than
# the grace period it is bounded by.
HOLD_SUMMARY_POLL_SECONDS = 600


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


def overdue_scan(*, now: datetime) -> Scan:
    """Send overdue-task digests to opted-in users as of ``now``.

    Starts from the work: each live community is asked once who has an overdue
    task, and only those accounts are read. Each one's tasks are then gathered
    from their own guild schemas with their membership context — no all-guild
    access.

    Both channels ship from this one pass: the digest email and a push. A user
    opted into either channel is a candidate, so turning email off doesn't
    silence push.
    """
    # Who has an overdue task anywhere, and in which communities.
    overdue: dict[int, list[int]] = {}

    async def _overdue_here(routed: AsyncSession, guild_id: int) -> None:
        for user_id in (
            await routed.exec(_overdue_assignments(TaskAssignee.user_id).distinct())
        ).scalars():
            overdue.setdefault(user_id, []).append(guild_id)

    async def _finish() -> None:
        if not overdue:
            logger.debug("overdue-digest: nothing overdue")
            return
        async with cohorts.system_session(None) as session:
            await set_rls_context(session)
            await _send_overdue(session, overdue, now=now)

    return Scan(Scope.LIVE, _overdue_here, _finish)


async def _send_overdue(
    session: AsyncSession, overdue: dict[int, list[int]], *, now: datetime
) -> None:
    """Send the digests of the accounts ``overdue`` names, in the communities
    it names them in."""
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
        tz = resolve_zone(user_tz)
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
        # Today's digest is claimed by stamping it before anything is sent, so
        # it goes out once however many processes sweep at the same moment.
        previous = user.last_overdue_notification_at
        claimed = await session.exec(
            sa_update(User)
            .where(
                User.id == user_id,
                or_(
                    User.last_overdue_notification_at.is_(None),
                    User.last_overdue_notification_at
                    < target_local.replace(hour=0, minute=0),
                ),
            )
            .values(last_overdue_notification_at=now)
        )
        await session.commit()
        if not claimed.rowcount:
            continue
        # A channel that is merely unconfigured (no SMTP, no FCM) hands the day
        # back below, so the next poll tries again instead of the user's one
        # digest being burnt. Preferences are re-read off the row just
        # reloaded, not the snapshot taken before the cross-guild gather, so a
        # channel switched off meanwhile stays quiet.
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
            await session.exec(
                sa_update(User)
                .where(
                    User.id == user_id,
                    User.last_overdue_notification_at == now,
                )
                .values(last_overdue_notification_at=previous)
            )
        await session.commit()


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
        # The account's settings row is held until its summary is recorded, and
        # the question asked again of what it holds now: a summary goes out
        # once however many processes sweep at the same moment.
        held = (
            await session.exec(
                select(UserNotificationPrefs)
                .where(UserNotificationPrefs.user_id == user.id)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        locked = dict(held.prefs or {}) if held is not None else None
        lift = (
            notification_prefs.last_lift(locked, tz_name=user.timezone, now=now)
            if locked is not None
            else None
        )
        if (
            locked is None
            or lift is None
            or _covered(_lift_stamps(locked), lift.kind, lift.closed)
        ):
            await session.commit()
            continue
        prefs = locked

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
        await session.commit()


async def process_hold_summaries() -> None:
    async with SystemSessionLocal() as session:
        await _run_hold_summary_pass(session, now=datetime.now(timezone.utc))


async def reminder_scan(*, now: datetime) -> Scan | None:
    """Dispatch lead-time reminders for upcoming calendar events, as of
    ``now``; ``None`` when nobody has asked for reminders.

    Considers events starting within the next day (the widest lead preset)
    whose attendees opted into reminders, and fires once per (event, user,
    start time) — keyed on ``start_at`` so a reschedule re-arms the reminder.
    Attendees who RSVP'd ``declined`` are skipped.

    Starts from what is due: each live community is asked once which opted-in
    attendees have a reminder due and unsent. Only those accounts are then
    routed into only those communities, with their own membership context, to
    dispatch reminders for the events they attend there.
    """
    horizon = now + timedelta(days=1)
    # Allow events that started within the grace window so a 0-minute
    # ("at the time of the event") reminder still fires on the next poll.
    lower = now - EVENT_REMINDER_GRACE
    # Asked of the system engine before any community is visited: a routed
    # session cannot read an account's preferences.
    users = await accounts_service.load_event_reminder_optins()
    lead = {
        account.id: timedelta(minutes=account.event_reminder_minutes_before)
        for account in users
        if account.id is not None and account.event_reminder_minutes_before is not None
    }
    if not lead:
        return None
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

    async def _dispatch(session: AsyncSession, guild_id: int, user_id: int) -> list:
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
        due = [(e.id, e.start_at) for e in events if e.start_at - lead[user_id] <= now]
        for event_id, start_at in due:
            # Reserve the dedup row before dispatching (reserve-then-send).
            # The reservation is the claim: a row already there — this pass's
            # earlier run, or another process sweeping now — means it is
            # somebody else's to send.
            reserved = await session.exec(
                pg_insert(EventReminderDispatch)
                .values(
                    event_id=event_id,
                    user_id=user_id,
                    event_start_at=start_at,
                    sent_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_nothing()
            )
            await session.commit()
            if not reserved.rowcount:
                continue
            event = (
                await session.exec(
                    select(CalendarEvent).where(CalendarEvent.id == event_id)
                )
            ).scalar_one_or_none()
            if event is None:
                continue  # deleted mid-run; dedup row stays so we don't retry
            await notify(
                session,
                NotificationType.event_reminder,
                [user_id],
                about=("calendar_event", event_id),
                key="event.reminder",
                values={
                    "event": event.title,
                    "when": lambda reader, _event=event: event_when(_event, reader),
                },
                data={"event_id": event_id, "start_at": start_at.isoformat()},
            )
            await session.commit()
        return []

    async def _finish() -> None:
        async with cohorts.system_session(None) as session:
            for user_id, guild_ids in due_in.items():
                # Through the seam, as the account whose reminders these are:
                # what the sweep may see of a community is what that account
                # may see.
                await gather_across_guilds(
                    session,
                    user_id,
                    await member_guild_ids(
                        session, user_id, restrict_to=sorted(guild_ids)
                    ),
                    lambda routed, gid, _uid=user_id: _dispatch(routed, gid, _uid),
                    satisfied_providers=SYSTEM_SATISFIED,
                    writes=True,
                )

    return Scan(Scope.LIVE, _visit, _finish)


# ── notices about your own account ───────────────────────────────────────────


async def queue_avatar_removed(session: AsyncSession, *, user: User) -> None:
    """Tell a user their profile picture was taken down.

    In-app only. There is no preference to consult and no email or push: this
    is not something a user opts out of being told, and it is not urgent enough
    to interrupt them on a device.

    Queues rather than sends: the caller commits, so the removal and the notice
    of it land together or not at all. A picture that vanished with no
    explanation is a support ticket.
    """
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.avatar_removed,
        data={"target_path": "/profile"},
    )


async def queue_username_changed(
    session: AsyncSession, *, user: User, previous_handle: str
) -> None:
    """Tell a user a moderator changed their username.

    Carries the handle they had, because the one they have is already on
    screen and the one they lost is what they will look for.

    In-app only, and queued rather than sent, for the same reasons as
    :func:`queue_avatar_removed`: not something to opt out of, not urgent
    enough to interrupt, and it lands with the change or not at all.
    """
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.username_changed,
        data={
            "previous_handle": previous_handle,
            "target_path": "/profile/account",
        },
    )


async def queue_account_suspended(
    session: AsyncSession, *, user: User, reason: str | None = None
) -> None:
    """Tell a user their account was suspended, and why if a reason was given.

    They can still sign in, which is the only reason telling them works: a
    suspension nobody could read would present as the app quietly breaking.
    """
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.account_suspended,
        data={"reason": reason, "target_path": "/profile/account"},
    )


async def queue_account_unsuspended(session: AsyncSession, *, user: User) -> None:
    """Tell a user their account is theirs again."""
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.account_unsuspended,
        data={"target_path": "/"},
    )
