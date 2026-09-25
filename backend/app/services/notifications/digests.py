"""Digested notification streams, and the task-assignment digest.

A digest queues a row per (recipient, event) in the guild the event happened
in, waits for the flurry to settle, then sends email and push together.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, delete, update as sa_update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import SYSTEM_SATISFIED, SystemSessionLocal, set_rls_context
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.core.tools import Tool
from app.core.notification_categories import (
    Channel,
    NotificationCategory,
    sample_type,
)
from app.models.tenant.task import Task
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.models.tenant.reaction_digest import ReactionDigestItem
from app.models.platform.user import User
from app.models.platform.notification import NotificationType
from app.services import email as email_service
from app.services.platform import email_outbox
from app.services.platform import notification_policy
from app.services.platform import notification_prefs
from app.services.platform import user_notifications
from app.services.platform import push_notifications
from app.services.notifications.delivery import (
    AppAuthor,
    MY_TASKS_TARGET_PATH,
    _build_smart_link,
    _channels,
    _nt,
    _recipient_locale,
    _task_target_path,
    actor_name,
)
from app.services.notifications.guild_walk import per_guild

logger = logging.getLogger(__name__)


DIGEST_POLL_SECONDS = 60


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


ASSIGNMENT_GC_POLL_SECONDS = 3600


async def enqueue_task_assignment_event(
    session: AsyncSession,
    *,
    task: Task,
    assignee: User,
    assigned_by: "User | AppAuthor",
    project_name: str,
    guild_id: int,
    initiative_id: int | None = None,
) -> None:
    if assignee.id == assigned_by.id:
        return
    target_path = _task_target_path(task.id, task.project_id)
    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    prefs = await notification_prefs.prefs_for_delivery(assignee)
    await user_notifications.create_notification(
        session,
        user_id=assignee.id,
        prefs=prefs,
        notification_type=NotificationType.task_assignment,
        data={
            "task_id": task.id,
            "project_id": task.project_id,
            "assigned_by_name": actor_name(assigned_by),
            "guild_id": guild_id,
            "initiative_id": initiative_id,
            "tool": Tool.project.value,
            "target_path": target_path,
            "smart_link": smart_link,
        },
    )
    # Email and push both ship from the digest worker on one schedule, so the
    # item is queued when EITHER channel is on; the worker re-reads both
    # preferences when it sends. Only the in-app notification above is
    # immediate — the bell is a list, not an interruption.
    if wants_assignment_digest(prefs, guild_id=guild_id):
        event = TaskAssignmentDigestItem(
            user_id=assignee.id,
            task_id=task.id,
            project_id=task.project_id,
            task_title=task.title,
            project_name=project_name,
            assigned_by_name=actor_name(assigned_by),
            assigned_by_id=assigned_by.id,
        )
        session.add(event)


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


async def _pending_digest_items(
    session: AsyncSession, model: type
) -> dict[int, dict[int, list[datetime]]]:
    """Who has unsent digest items, where, and when the first and last came:
    ``{user_id: {guild_id: [first, last]}}``."""
    pending: dict[int, dict[int, list[datetime]]] = {}

    async def _visit(routed: AsyncSession, guild_id: int) -> None:
        rows = (
            await routed.exec(
                select(
                    model.user_id,
                    func.min(model.created_at),
                    func.max(model.created_at),
                )
                .where(model.processed_at.is_(None))
                .group_by(model.user_id)
            )
        ).all()
        for user_id, first, last in rows:
            pending.setdefault(user_id, {})[guild_id] = [first, last]

    await per_guild(session, _visit)
    return pending


async def _run_digest_pass(
    session: AsyncSession, spec: DigestSpec, *, now: datetime
) -> None:
    """Send ``spec``'s digest to opted-in users as of ``now``.

    Starts from what is waiting: each community is asked once which accounts
    have unsent items, and only the accounts whose items have settled go any
    further. Their items are then gathered with their own membership context
    (not the guild's role) and marked processed back in each schema. Email and
    push ship together, on the same trigger, so the two channels tell the same
    story — see :func:`_digest_is_due` for the timing.
    """
    model = spec.model
    pending = await _pending_digest_items(session, model)
    if not pending:
        logger.debug("%s: nothing pending", spec.name)
        return
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
        per_guild_items: dict[int, list[int]] = {}

        # Capture user_id / per_guild_items as defaults so this closure doesn't
        # bind the loop variables by reference (B023) — safe even if the call
        # site is ever refactored to defer the closures.
        async def _fetch(
            routed: AsyncSession,
            gid: int,
            *,
            _uid=user_id,
            _items=per_guild_items,
        ) -> list[dict]:
            # A community set to say less is filtered here, where the guild is
            # known — a digest spans guilds, so this cannot be decided once for
            # the whole batch.
            if not wants_digest(all_prefs.get(_uid), spec.category, guild_id=gid):
                _items[gid] = []
                return []
            items = (
                (
                    await routed.exec(
                        select(model)
                        .where(
                            model.user_id == _uid,
                            model.processed_at.is_(None),
                        )
                        .order_by(model.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )
            _items[gid] = [item.id for item in items]
            return [spec.row(item, gid) for item in items]

        # Only the communities holding something for them, and only while they
        # still belong to it.
        guild_ids = await member_guild_ids(session, user_id, restrict_to=list(held))
        # Digests act on membership (no live session exists here) — the
        # system sentinel clears the guild auth-policy gate.
        batch = await gather_across_guilds(
            session, user_id, guild_ids, _fetch, satisfied_providers=SYSTEM_SATISFIED
        )
        if not batch:
            continue
        # Send: re-load the user (gather expunged it) in a shared-table context.
        session.expunge_all()
        await set_rls_context(session, user_id=user_id)
        user = (
            await session.exec(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if (
            user is None
        ):  # deleted between the snapshot and now — skip, don't abort the pass
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
            if delivered:
                logger.info(
                    "%s: queued %d item(s) for user %s",
                    spec.name,
                    len(email_batch),
                    user_id,
                )
            else:
                logger.warning(
                    "SMTP not configured; holding %s for %s", spec.name, user_id
                )
        if channels.push and push_batch:
            pushed, push_retry = await spec.send_push(session, user, push_batch)
            delivered = delivered or pushed
            retry = retry or push_retry
        if retry and not delivered:
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
        # Mark the gathered items processed, back in each guild's schema.
        for gid, item_ids in per_guild_items.items():
            if not item_ids:
                continue
            session.expunge_all()
            # Nobody is asking: the rows were gathered under this account's own
            # standing above, and marking them consumed is the sweep's write.
            await set_rls_context(session, guild_id=gid)
            await session.exec(
                sa_update(model).where(model.id.in_(item_ids)).values(processed_at=now)
            )
            await session.commit()
        if spec.stamp is None:
            continue
        session.expunge_all()
        await set_rls_context(session, user_id=user_id)
        user = (
            await session.exec(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            continue
        setattr(user, spec.stamp, now)
        session.add(user)
        await session.commit()


async def _run_gc_pass(
    session: AsyncSession, models: Sequence[type], *, now: datetime
) -> None:
    """Drop digest items older than the retention window, guild by guild.

    Sent items are bookkeeping once the mail is gone. Unsent items of the same
    age are dropped too: they are either orphaned (the user turned the channel
    off in a guild an admin could not reach) or so stale that announcing them
    would be noise.
    """
    cutoff = now - ASSIGNMENT_ITEM_RETENTION

    async def _visit(routed: AsyncSession, _guild_id: int) -> None:
        for model in models:
            await routed.exec(delete(model).where(model.created_at < cutoff))

    await per_guild(session, _visit)


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


async def _run_assignment_digest_pass(session: AsyncSession, *, now: datetime) -> None:
    """Send task-assignment digests. Split out from
    ``process_task_assignment_digests`` so tests can drive it with the test
    session."""
    await _run_digest_pass(session, ASSIGNMENT_DIGEST, now=now)


async def process_task_assignment_digests() -> None:
    async with SystemSessionLocal() as session:
        await _run_assignment_digest_pass(session, now=datetime.now(timezone.utc))


async def _run_assignment_gc_pass(session: AsyncSession, *, now: datetime) -> None:
    await _run_gc_pass(session, (TaskAssignmentDigestItem, ReactionDigestItem), now=now)
    # Mail that has gone out, or run out of attempts, is bookkeeping on the
    # same terms as a spent digest row — so it goes in the same sweep rather
    # than growing a second one.
    await set_rls_context(session)
    dropped = await email_outbox.sweep_settled(session, now=now)
    if dropped:
        logger.info("digest-gc: dropped %d settled email row(s)", dropped)
    await session.commit()
    # Read notifications past their retention go on the same hourly sweep.
    pruned = await user_notifications.prune_read(session, now=now)
    if pruned:
        logger.info("digest-gc: deleted %d read notification(s)", pruned)


async def process_assignment_digest_gc() -> None:
    async with SystemSessionLocal() as session:
        await set_rls_context(session)
        await _run_assignment_gc_pass(session, now=datetime.now(timezone.utc))
