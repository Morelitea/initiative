from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select, delete, update as sa_update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.email_i18n import email_t, translate
from app.db.session import SYSTEM_SATISFIED, AdminSessionLocal, set_rls_context
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.core.config import settings as app_config
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.models.tenant.reaction_digest import ReactionDigestItem
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
    RSVPStatus,
)
from app.models.tenant.event_reminder_dispatch import EventReminderDispatch
from app.models.platform.guild import Guild, GuildStatus
from app.models.platform.user import User
from app.services.platform import accounts as accounts_service
from app.models.platform.notification import NotificationType
from app.services import email as email_service
from app.services.platform import user_notifications
from app.services.platform import push_notifications
from app.core.user_display import handle_of

# A notification is read on the cross-guild ``/me/notifications`` surface,
# away from the guild it was written in, so the people it names are named by
# their handle rather than by whatever that one guild renders. The handle is
# the identifier that reads the same everywhere and needs no permission
# resolved at the moment someone opens the list.

logger = logging.getLogger(__name__)

DIGEST_POLL_SECONDS = 60
OVERDUE_POLL_SECONDS = 300
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
EVENT_REMINDER_POLL_SECONDS = 60
# Events that started within this window are still eligible, so a 0-minute
# ("at start") reminder fires on the next poll rather than being missed.
EVENT_REMINDER_GRACE = timedelta(minutes=5)
# My Tasks is the app root: the cross-guild list of everything assigned to you.
# Cross-guild notifications point here instead of at one guild's copy.
MY_TASKS_TARGET_PATH = "/"


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
def _entity_ref_path(ref_type: str, entity_id: int) -> str:
    return f"/go/{ref_type}/{entity_id}"


def _document_target_path(document_id: int | None) -> str:
    if document_id is None:
        return "/"
    return _entity_ref_path("document", document_id)


def _task_target_path(task_id: int | None, project_id: int | None) -> str:
    if task_id:
        return _entity_ref_path("task", task_id)
    if project_id:
        return _entity_ref_path("project", project_id)
    # No entity to resolve — the guild home is the only honest landing spot now
    # that there is no guild-wide project list.
    return "/"


def _project_target_path(project_id: int | None) -> str:
    if project_id is None:
        return "/"
    return _entity_ref_path("project", project_id)


def _tool_target_path(entity_type: str, entity_id: int) -> str:
    """A tool entity's reference path — the ref type is the tool's kebab
    singular (``counter_group`` → ``counter-group``), which is what the
    client's resolver speaks."""
    return _entity_ref_path(entity_type.replace("_", "-"), entity_id)


def _event_target_path(event_id: int | None) -> str:
    if event_id is None:
        return "/"
    return _entity_ref_path("event", event_id)


def _initiative_target_path(initiative_id: int | None) -> str:
    if initiative_id is None:
        # No one initiative to open, so land on the guild's front page — which
        # is where the initiative list lives now that the standalone page is
        # gone. "/i" would only redirect here anyway.
        return "/"
    return f"/i/{initiative_id}"


# Public spellings of the three path builders above. Another service that
# addresses the same entity must produce the IDENTICAL path — a notification
# and a reaction digest pointing at the same comment must land in the same
# place — so it calls these rather than deriving its own.
task_target_path = _task_target_path
document_target_path = _document_target_path
tool_target_path = _tool_target_path


def _recipient_locale(user: User) -> str:
    return getattr(user, "locale", None) or "en"


def _nt(key: str, locale: str, **kwargs: str | int) -> str:
    """Translate a push string from the ``notifications`` namespace.

    Push notifications carry only a ``title`` and ``body``. Email copy for the
    same events lives in the ``email`` namespace (``email_t``); the two are kept
    separate because their wording differs (push is terse, email is richer).
    """
    return translate(key, locale, namespace="notifications", **kwargs)


async def enqueue_task_assignment_event(
    session: AsyncSession,
    *,
    task: Task,
    assignee: User,
    assigned_by: User,
    project_name: str,
    guild_id: int,
) -> None:
    if assignee.id == assigned_by.id:
        return
    target_path = _task_target_path(task.id, task.project_id)
    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    # Always create in-app notification
    await user_notifications.create_notification(
        session,
        user_id=assignee.id,
        notification_type=NotificationType.task_assignment,
        data={
            "task_id": task.id,
            "task_title": task.title,
            "project_id": task.project_id,
            "project_name": project_name,
            "assigned_by_name": handle_of(assigned_by),
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": smart_link,
        },
    )
    # Email and push both ship from the digest worker on one schedule, so the
    # item is queued when EITHER channel is on; the worker re-reads both
    # preferences when it sends. Only the in-app notification above is
    # immediate — the bell is a list, not an interruption.
    if (
        assignee.email_task_assignment is not False
        or assignee.push_task_assignment is not False
    ):
        event = TaskAssignmentDigestItem(
            user_id=assignee.id,
            task_id=task.id,
            project_id=task.project_id,
            task_title=task.title,
            project_name=project_name,
            assigned_by_name=handle_of(assigned_by),
            assigned_by_id=assigned_by.id,
        )
        session.add(event)


def wants_assignment_digest(email_pref: bool | None, push_pref: bool | None) -> bool:
    """Whether a user still wants the assignment digest on either channel."""
    return wants_digest(email_pref, push_pref)


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


async def clear_task_assignment_queue_for_user(
    session: AsyncSession, user_id: int
) -> None:
    """The assignment queue alone, in the currently routed guild schema."""
    await clear_digest_queue_for_user(session, user_id, (TaskAssignmentDigestItem,))


async def clear_digest_queue_across_guilds(
    session: AsyncSession, user_id: int, models: Sequence[type]
) -> None:
    """Platform-path variant: a digest queue is guild-scoped, so visit each
    of the user's guild schemas. Leaves the session routed into the last guild
    and the identity map expunged — the caller restores its own context.
    Deletes are flushed, not committed; they ride the caller's transaction."""
    from app.services import cross_guild

    guild_ids = await cross_guild.member_guild_ids(session, user_id)

    async def _clear(routed: AsyncSession, _gid: int) -> list:
        await clear_digest_queue_for_user(routed, user_id, models)
        return []

    # Membership-based hygiene, not content access: must reach every guild
    # the user belongs to, including auth-policy-gated ones.
    await cross_guild.gather_across_guilds(
        session, user_id, guild_ids, _clear, satisfied_providers=SYSTEM_SATISFIED
    )


async def clear_task_assignment_queue_across_guilds(
    session: AsyncSession, user_id: int
) -> None:
    """The assignment queue alone, across every guild the user belongs to."""
    await clear_digest_queue_across_guilds(
        session, user_id, (TaskAssignmentDigestItem,)
    )


async def notify_initiative_membership(
    session: AsyncSession,
    user: User,
    initiative_id: int,
    initiative_name: str,
    guild_id: int,
) -> None:
    target_path = _initiative_target_path(initiative_id)
    # Always create in-app notification
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.initiative_added,
        data={
            "initiative_id": initiative_id,
            "initiative_name": initiative_name,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
        },
    )
    # Email
    if user.email_initiative_addition is not False:
        try:
            await email_service.send_initiative_added_email(
                session, user, initiative_name
            )
        except email_service.EmailNotConfiguredError:
            logger.warning(
                "SMTP not configured; skipping initiative notification for %s",
                user.email,
            )
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send initiative notification: %s", exc)
    # Push notification
    if user.push_initiative_addition is not False:
        locale = _recipient_locale(user)
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=user.id,
                notification_type=NotificationType.initiative_added,
                title=_nt("initiative.added.title", locale),
                body=_nt("initiative.added.body", locale, initiative=initiative_name),
                data={
                    "type": "initiative_added",
                    "initiative_id": str(initiative_id),
                    "guild_id": str(guild_id),
                    "target_path": target_path,
                },
            )
        except Exception as exc:
            logger.error(f"Failed to send push notification: {exc}", exc_info=True)
    await session.commit()


async def _send_join_request_push(
    session: AsyncSession,
    recipient: User,
    *,
    notification_type: NotificationType,
    title_key: str,
    body_key: str,
    target_path: str,
    guild_id: int,
    initiative_id: int,
    **body_vars: str,
) -> None:
    """Push half of the join-request notifications, best effort.

    Gated on ``push_initiative_addition``: all three events are news about the
    recipient's initiative membership — asked for, granted, or refused — so they
    honour the preference that already governs that topic rather than adding a
    fourth toggle for the same idea.
    """
    if recipient.push_initiative_addition is False:
        return
    locale = _recipient_locale(recipient)
    try:
        await push_notifications.send_push_to_user(
            session=session,
            user_id=recipient.id,
            notification_type=notification_type,
            title=_nt(title_key, locale),
            body=_nt(body_key, locale, **body_vars),
            data={
                "type": notification_type.value,
                "initiative_id": str(initiative_id),
                "guild_id": str(guild_id),
                "target_path": target_path,
            },
        )
    except Exception as exc:
        logger.error("Failed to send push notification: %s", exc, exc_info=True)


async def _send_join_request_email(
    session: AsyncSession,
    recipient: User,
    *,
    event: str,
    initiative_name: str,
    target_path: str,
    guild_id: int,
    requester: str | None = None,
    message: str | None = None,
) -> None:
    """Email half of the join-request notifications, best effort.

    Gated on ``email_initiative_addition`` for the same reason the push half is
    gated on its counterpart: all three events are news about the recipient's
    initiative membership, so they honour the preference that already governs
    that topic instead of growing a second toggle for the same idea.

    The link is the guild-aware smart link — these events mean nothing outside
    the guild they happened in.
    """
    if recipient.email_initiative_addition is False:
        return
    link = (
        _build_smart_link(target_path=target_path, guild_id=guild_id)
        or app_config.APP_URL
    )
    try:
        await email_service.send_initiative_join_request_email(
            session,
            recipient,
            event=event,
            initiative_name=initiative_name,
            link=link,
            requester=requester,
            message=message,
        )
    except email_service.EmailNotConfiguredError:
        logger.warning(
            "SMTP not configured; skipping join-request email for %s", recipient.email
        )
    except Exception as exc:
        logger.error("Failed to send join-request email: %s", exc, exc_info=True)


async def notify_initiative_join_requested(
    session: AsyncSession,
    managers: list[User],
    *,
    request_id: int,
    initiative_id: int,
    initiative_name: str,
    guild_id: int,
    requester: User,
    message: str | None = None,
) -> None:
    """Tell an initiative's managers that someone knocked.

    Addressed to the people who can answer it — the manager-role members — and
    it carries no initiative *content*, only who asked, what they said, and
    where to answer.
    """
    # Straight to the queue rather than the initiative: the recipient was told
    # about this to act on it, and only a manager is ever sent one.
    target_path = f"{_initiative_target_path(initiative_id)}/settings/members"
    requester_name = handle_of(requester)
    for manager in managers:
        await user_notifications.create_notification(
            session,
            user_id=manager.id,
            notification_type=NotificationType.initiative_join_requested,
            data={
                "request_id": request_id,
                "initiative_id": initiative_id,
                "initiative_name": initiative_name,
                "guild_id": guild_id,
                "requester_id": requester.id,
                "requester_name": requester_name,
                "target_path": target_path,
                "smart_link": _build_smart_link(
                    target_path=target_path, guild_id=guild_id
                ),
            },
        )
        await _send_join_request_push(
            session,
            manager,
            notification_type=NotificationType.initiative_join_requested,
            title_key="initiative.joinRequested.title",
            body_key="initiative.joinRequested.body",
            target_path=target_path,
            guild_id=guild_id,
            initiative_id=initiative_id,
            requester=requester_name,
            initiative=initiative_name,
        )
        await _send_join_request_email(
            session,
            manager,
            event="requested",
            initiative_name=initiative_name,
            target_path=target_path,
            guild_id=guild_id,
            requester=requester_name,
            message=message,
        )
    await session.commit()


async def notify_initiative_join_resolved(
    session: AsyncSession,
    requester: User,
    *,
    request_id: int,
    initiative_id: int,
    initiative_name: str,
    guild_id: int,
    approved: bool,
) -> None:
    """Tell the requester how their knock was answered.

    An approval points at the initiative — the membership row now exists, so the
    link resolves. A denial points at the directory instead, which is as far as
    they can go.
    """
    notification_type = (
        NotificationType.initiative_join_approved
        if approved
        else NotificationType.initiative_join_denied
    )
    target_path = (
        _initiative_target_path(initiative_id)
        if approved
        else _initiative_target_path(None)
    )
    await user_notifications.create_notification(
        session,
        user_id=requester.id,
        notification_type=notification_type,
        data={
            "request_id": request_id,
            "initiative_id": initiative_id,
            "initiative_name": initiative_name,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
        },
    )
    await _send_join_request_push(
        session,
        requester,
        notification_type=notification_type,
        title_key=(
            "initiative.joinApproved.title"
            if approved
            else "initiative.joinDenied.title"
        ),
        body_key=(
            "initiative.joinApproved.body" if approved else "initiative.joinDenied.body"
        ),
        target_path=target_path,
        guild_id=guild_id,
        initiative_id=initiative_id,
        initiative=initiative_name,
    )
    await _send_join_request_email(
        session,
        requester,
        event="approved" if approved else "denied",
        initiative_name=initiative_name,
        target_path=target_path,
        guild_id=guild_id,
    )
    await session.commit()


async def notify_project_added(
    session: AsyncSession,
    user: User,
    *,
    initiative_name: str,
    project_name: str,
    project_id: int,
    initiative_id: int,
    guild_id: int,
) -> None:
    target_path = _project_target_path(project_id)
    # Always create in-app notification
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.project_added,
        data={
            "initiative_id": initiative_id,
            "initiative_name": initiative_name,
            "project_id": project_id,
            "project_name": project_name,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": _build_smart_link(
                target_path=target_path,
                guild_id=guild_id,
            ),
        },
    )
    # Email
    if user.email_project_added is not False:
        try:
            await email_service.send_project_added_to_initiative_email(
                session,
                user,
                initiative_name=initiative_name,
                project_name=project_name,
                project_id=project_id,
            )
        except email_service.EmailNotConfiguredError:
            logger.warning(
                "SMTP not configured; skipping project notification for %s", user.email
            )
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send project notification: %s", exc)
    # Push notification
    if user.push_project_added is not False:
        locale = _recipient_locale(user)
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=user.id,
                notification_type=NotificationType.project_added,
                title=_nt("project.added.title", locale),
                body=_nt(
                    "project.added.body",
                    locale,
                    project=project_name,
                    initiative=initiative_name,
                ),
                data={
                    "type": "project_added",
                    "project_id": str(project_id),
                    "guild_id": str(guild_id),
                    "target_path": target_path,
                },
            )
        except Exception as exc:
            logger.error(f"Failed to send push notification: {exc}", exc_info=True)
    await session.commit()


async def notify_document_mention(
    session: AsyncSession,
    *,
    mentioned_user: User,
    mentioned_by: User,
    document_id: int,
    document_name: str,
    guild_id: int,
) -> None:
    """Notify a user they were mentioned in a document."""
    if mentioned_user.id == mentioned_by.id:
        return
    target_path = _document_target_path(document_id)
    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    mentioned_by_name = handle_of(mentioned_by)
    locale = _recipient_locale(mentioned_user)
    # Always create in-app notification
    await user_notifications.create_notification(
        session,
        user_id=mentioned_user.id,
        notification_type=NotificationType.mention,
        data={
            "document_id": document_id,
            "document_name": document_name,
            "mentioned_by_name": mentioned_by_name,
            "mentioned_by_id": mentioned_by.id,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": smart_link,
        },
    )
    # Email
    if getattr(mentioned_user, "email_mentions", True) is not False:
        try:
            await email_service.send_mention_email(
                session,
                mentioned_user,
                subject=email_t(
                    "mention.document.subject",
                    locale,
                    document=document_name,
                    escape=False,
                ),
                headline=email_t("mention.document.title", locale),
                body_text=email_t(
                    "mention.document.body",
                    locale,
                    actor=mentioned_by_name,
                    document=document_name,
                ),
                link=smart_link,
            )
        except email_service.EmailNotConfiguredError:
            logger.warning(
                "SMTP not configured; skipping mention email for %s",
                mentioned_user.email,
            )
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send mention email: %s", exc)
    # Push notification
    if getattr(mentioned_user, "push_mentions", True) is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=mentioned_user.id,
                notification_type=NotificationType.mention,
                title=_nt("mention.document.title", locale),
                body=_nt(
                    "mention.document.body",
                    locale,
                    actor=mentioned_by_name,
                    document=document_name,
                ),
                data={
                    "type": "mention",
                    "document_id": str(document_id),
                    "guild_id": str(guild_id),
                    "target_path": target_path,
                },
            )
        except Exception as exc:
            logger.error(f"Failed to send push notification: {exc}", exc_info=True)


async def notify_comment_mention(
    session: AsyncSession,
    *,
    mentioned_user: User,
    mentioned_by: User,
    comment_id: int,
    task_id: int | None,
    document_id: int | None,
    context_title: str,
    guild_id: int,
    entity_type: str | None = None,
    entity_id: int | None = None,
) -> None:
    """Notify a user they were mentioned in a comment. ``entity_type``/
    ``entity_id`` name the parent when it is a tool entity other than a
    document (a project, queue, counter group, calendar, or dashboard)."""
    if mentioned_user.id == mentioned_by.id:
        return

    if task_id:
        target_path = _task_target_path(task_id, None)
    elif document_id:
        target_path = _document_target_path(document_id)
    elif entity_type and entity_id:
        target_path = _tool_target_path(entity_type, entity_id)
    else:
        return

    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    mentioned_by_name = handle_of(mentioned_by)
    locale = _recipient_locale(mentioned_user)

    # Always create in-app notification
    await user_notifications.create_notification(
        session,
        user_id=mentioned_user.id,
        notification_type=NotificationType.mention,
        data={
            "comment_id": comment_id,
            "task_id": task_id,
            "document_id": document_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "context_title": context_title,
            "mentioned_by_name": mentioned_by_name,
            "mentioned_by_id": mentioned_by.id,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": smart_link,
        },
    )
    # Email
    if getattr(mentioned_user, "email_mentions", True) is not False:
        try:
            await email_service.send_mention_email(
                session,
                mentioned_user,
                subject=email_t("mention.comment.subject", locale, escape=False),
                headline=email_t("mention.comment.title", locale),
                body_text=email_t(
                    "mention.comment.body",
                    locale,
                    actor=mentioned_by_name,
                    context=context_title,
                ),
                link=smart_link,
            )
        except email_service.EmailNotConfiguredError:
            logger.warning(
                "SMTP not configured; skipping mention email for %s",
                mentioned_user.email,
            )
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send mention email: %s", exc)
    # Push notification
    if getattr(mentioned_user, "push_mentions", True) is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=mentioned_user.id,
                notification_type=NotificationType.mention,
                title=_nt("mention.comment.title", locale),
                body=_nt(
                    "mention.comment.body",
                    locale,
                    actor=mentioned_by_name,
                    context=context_title,
                ),
                data={
                    "type": "mention",
                    "comment_id": str(comment_id),
                    "task_id": str(task_id) if task_id else None,
                    "document_id": str(document_id) if document_id else None,
                    "guild_id": str(guild_id),
                    "target_path": target_path,
                },
            )
        except Exception as exc:
            logger.error(f"Failed to send push notification: {exc}", exc_info=True)


async def notify_task_mentioned_in_comment(
    session: AsyncSession,
    *,
    assignee: User,
    mentioned_by: User,
    comment_id: int,
    mentioned_task_id: int,
    mentioned_task_title: str,
    context_task_id: int | None,
    context_document_id: int | None,
    context_title: str,
    guild_id: int,
    context_entity_type: str | None = None,
    context_entity_id: int | None = None,
) -> None:
    """Notify task assignee that their task was mentioned in a comment."""
    if assignee.id == mentioned_by.id:
        return

    if context_task_id:
        target_path = _task_target_path(context_task_id, None)
    elif context_document_id:
        target_path = _document_target_path(context_document_id)
    elif context_entity_type and context_entity_id:
        target_path = _tool_target_path(context_entity_type, context_entity_id)
    else:
        return

    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    mentioned_by_name = handle_of(mentioned_by)
    locale = _recipient_locale(assignee)

    # Always create in-app notification
    await user_notifications.create_notification(
        session,
        user_id=assignee.id,
        notification_type=NotificationType.mention,
        data={
            "comment_id": comment_id,
            "mentioned_task_id": mentioned_task_id,
            "mentioned_task_title": mentioned_task_title,
            "context_task_id": context_task_id,
            "context_document_id": context_document_id,
            "context_entity_type": context_entity_type,
            "context_entity_id": context_entity_id,
            "context_title": context_title,
            "mentioned_by_name": mentioned_by_name,
            "mentioned_by_id": mentioned_by.id,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": smart_link,
        },
    )
    # Email
    if getattr(assignee, "email_mentions", True) is not False:
        try:
            await email_service.send_mention_email(
                session,
                assignee,
                subject=email_t("mention.task.subject", locale, escape=False),
                headline=email_t("mention.task.title", locale),
                body_text=email_t(
                    "mention.task.body",
                    locale,
                    actor=mentioned_by_name,
                    task=mentioned_task_title,
                    context=context_title,
                ),
                link=smart_link,
            )
        except email_service.EmailNotConfiguredError:
            logger.warning(
                "SMTP not configured; skipping mention email for %s", assignee.email
            )
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send mention email: %s", exc)
    # Push notification
    if getattr(assignee, "push_mentions", True) is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=assignee.id,
                notification_type=NotificationType.mention,
                title=_nt("mention.task.title", locale),
                body=_nt(
                    "mention.task.body",
                    locale,
                    actor=mentioned_by_name,
                    task=mentioned_task_title,
                    context=context_title,
                ),
                data={
                    "type": "mention",
                    "comment_id": str(comment_id),
                    "mentioned_task_id": str(mentioned_task_id),
                    "guild_id": str(guild_id),
                    "target_path": target_path,
                },
            )
        except Exception as exc:
            logger.error(f"Failed to send push notification: {exc}", exc_info=True)


async def notify_comment_on_task(
    session: AsyncSession,
    *,
    assignee: User,
    commenter: User,
    comment_id: int,
    task_id: int,
    task_title: str,
    project_name: str,
    guild_id: int,
) -> None:
    """Notify task assignee that someone commented on their task."""
    if assignee.id == commenter.id:
        return

    target_path = _task_target_path(task_id, None)
    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    commenter_name = handle_of(commenter)
    locale = _recipient_locale(assignee)

    # Always create in-app notification
    await user_notifications.create_notification(
        session,
        user_id=assignee.id,
        notification_type=NotificationType.comment_on_task,
        data={
            "comment_id": comment_id,
            "task_id": task_id,
            "task_title": task_title,
            "project_name": project_name,
            "commenter_name": commenter_name,
            "commenter_id": commenter.id,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": smart_link,
        },
    )
    # Email
    if getattr(assignee, "email_mentions", True) is not False:
        try:
            await email_service.send_mention_email(
                session,
                assignee,
                subject=email_t(
                    "comment.onTask.subject", locale, task=task_title, escape=False
                ),
                headline=email_t("comment.onTask.title", locale),
                body_text=email_t(
                    "comment.onTask.body", locale, actor=commenter_name, task=task_title
                ),
                link=smart_link,
            )
        except email_service.EmailNotConfiguredError:
            logger.warning(
                "SMTP not configured; skipping comment email for %s", assignee.email
            )
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send comment email: %s", exc)
    # Push notification
    if getattr(assignee, "push_mentions", True) is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=assignee.id,
                notification_type=NotificationType.comment_on_task,
                title=_nt("comment.onTask.title", locale),
                body=_nt(
                    "comment.onTask.body", locale, actor=commenter_name, task=task_title
                ),
                data={
                    "type": "comment_on_task",
                    "comment_id": str(comment_id),
                    "task_id": str(task_id),
                    "guild_id": str(guild_id),
                    "target_path": target_path,
                },
            )
        except Exception as exc:
            logger.error(f"Failed to send push notification: {exc}", exc_info=True)


async def notify_comment_on_resource(
    session: AsyncSession,
    *,
    owner: User,
    commenter: User,
    comment_id: int,
    entity_type: str,
    entity_id: int,
    entity_name: str,
    guild_id: int,
) -> None:
    """Notify a tool entity's creator that someone commented on it.

    One notification for every tool parent — project, document, queue,
    counter group, calendar, dashboard. ``entity_type`` is the Tool value.
    """
    if owner.id == commenter.id:
        return

    target_path = _tool_target_path(entity_type, entity_id)
    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    commenter_name = handle_of(commenter)
    locale = _recipient_locale(owner)

    # Always create in-app notification
    await user_notifications.create_notification(
        session,
        user_id=owner.id,
        notification_type=NotificationType.comment_on_resource,
        data={
            "comment_id": comment_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "commenter_name": commenter_name,
            "commenter_id": commenter.id,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": smart_link,
        },
    )
    # Email
    if getattr(owner, "email_mentions", True) is not False:
        try:
            await email_service.send_mention_email(
                session,
                owner,
                subject=email_t(
                    "comment.onResource.subject",
                    locale,
                    context=entity_name,
                    escape=False,
                ),
                headline=email_t("comment.onResource.title", locale),
                body_text=email_t(
                    "comment.onResource.body",
                    locale,
                    actor=commenter_name,
                    context=entity_name,
                ),
                link=smart_link,
            )
        except email_service.EmailNotConfiguredError:
            logger.warning(
                "SMTP not configured; skipping comment email for %s", owner.email
            )
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send comment email: %s", exc)
    # Push notification
    if getattr(owner, "push_mentions", True) is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=owner.id,
                notification_type=NotificationType.comment_on_resource,
                title=_nt("comment.onResource.title", locale),
                body=_nt(
                    "comment.onResource.body",
                    locale,
                    actor=commenter_name,
                    context=entity_name,
                ),
                data={
                    "type": "comment_on_resource",
                    "comment_id": str(comment_id),
                    "entity_type": entity_type,
                    "entity_id": str(entity_id),
                    "guild_id": str(guild_id),
                    "target_path": target_path,
                },
            )
        except Exception as exc:
            logger.error(f"Failed to send push notification: {exc}", exc_info=True)


async def notify_comment_reply(
    session: AsyncSession,
    *,
    parent_author: User,
    replier: User,
    comment_id: int,
    task_id: int | None,
    document_id: int | None,
    context_title: str,
    guild_id: int,
    entity_type: str | None = None,
    entity_id: int | None = None,
) -> None:
    """Notify parent comment author that someone replied to their comment."""
    if parent_author.id == replier.id:
        return

    if task_id:
        target_path = _task_target_path(task_id, None)
    elif document_id:
        target_path = _document_target_path(document_id)
    elif entity_type and entity_id:
        target_path = _tool_target_path(entity_type, entity_id)
    else:
        return

    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    replier_name = handle_of(replier)
    locale = _recipient_locale(parent_author)

    # Always create in-app notification
    await user_notifications.create_notification(
        session,
        user_id=parent_author.id,
        notification_type=NotificationType.comment_reply,
        data={
            "comment_id": comment_id,
            "task_id": task_id,
            "document_id": document_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "context_title": context_title,
            "replier_name": replier_name,
            "replier_id": replier.id,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": smart_link,
        },
    )
    # Email
    if getattr(parent_author, "email_mentions", True) is not False:
        try:
            await email_service.send_mention_email(
                session,
                parent_author,
                subject=email_t("comment.reply.subject", locale, escape=False),
                headline=email_t("comment.reply.title", locale),
                body_text=email_t(
                    "comment.reply.body",
                    locale,
                    actor=replier_name,
                    context=context_title,
                ),
                link=smart_link,
            )
        except email_service.EmailNotConfiguredError:
            logger.warning(
                "SMTP not configured; skipping reply email for %s", parent_author.email
            )
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send reply email: %s", exc)
    # Push notification
    if getattr(parent_author, "push_mentions", True) is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=parent_author.id,
                notification_type=NotificationType.comment_reply,
                title=_nt("comment.reply.title", locale),
                body=_nt(
                    "comment.reply.body",
                    locale,
                    actor=replier_name,
                    context=context_title,
                ),
                data={
                    "type": "comment_reply",
                    "comment_id": str(comment_id),
                    "task_id": str(task_id) if task_id else None,
                    "document_id": str(document_id) if document_id else None,
                    "guild_id": str(guild_id),
                    "target_path": target_path,
                },
            )
        except Exception as exc:
            logger.error(f"Failed to send push notification: {exc}", exc_info=True)


# ---------------------------------------------------------------------------
# Calendar event notifications
# ---------------------------------------------------------------------------


def _format_event_when(event: CalendarEvent, recipient: User) -> str:
    """Human-readable event start, localized to the recipient's timezone.

    All-day events show just the date; timed events convert the stored UTC
    instant into the recipient's IANA timezone and append the zone abbrev
    (e.g. ``Wed, Jul 1, 2026 at 2:30 PM PDT``).
    """
    if event.all_day:
        return event.start_at.strftime("%a, %b %-d, %Y")
    tz = _resolve_timezone(recipient.timezone)
    local = event.start_at.astimezone(tz)
    return local.strftime("%a, %b %-d, %Y at %-I:%M %p %Z")


async def _deliver_event_notification(
    session: AsyncSession,
    *,
    recipient: User,
    notification_type: NotificationType,
    data: dict,
    email_enabled: bool,
    push_enabled: bool,
    email_subject: str,
    email_headline: str,
    email_body: str,
    push_title: str,
    push_body: str,
) -> None:
    """Shared 3-tier delivery for calendar-event notifications.

    In-app is always created; email/push are gated by the caller's resolved
    preference flags. Mirrors the task/comment notifiers' structure.
    """
    target_path = data.get("target_path", "/")
    guild_id = data.get("guild_id")
    await user_notifications.create_notification(
        session,
        user_id=recipient.id,
        notification_type=notification_type,
        data=data,
    )
    if email_enabled:
        try:
            await email_service.send_mention_email(
                session,
                recipient,
                subject=email_subject,
                headline=email_headline,
                body_text=email_body,
                link=data.get("smart_link"),
            )
        except email_service.EmailNotConfiguredError:
            logger.warning(
                "SMTP not configured; skipping event email for %s", recipient.email
            )
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send event email: %s", exc)
    if push_enabled:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=recipient.id,
                notification_type=notification_type,
                title=push_title,
                body=push_body,
                data={
                    "type": notification_type.value,
                    "event_id": str(data.get("event_id")),
                    "guild_id": str(guild_id),
                    "target_path": target_path,
                },
            )
        except Exception as exc:
            logger.error(f"Failed to send push notification: {exc}", exc_info=True)


def _event_data(event: CalendarEvent, guild_id: int, **extra) -> dict:
    target_path = _event_target_path(event.id)
    data = {
        "event_id": event.id,
        "event_title": event.title,
        "start_at": event.start_at.isoformat(),
        "guild_id": guild_id,
        "target_path": target_path,
        "smart_link": _build_smart_link(target_path=target_path, guild_id=guild_id),
    }
    data.update(extra)
    return data


async def notify_event_invitation(
    session: AsyncSession,
    *,
    attendee: User,
    organizer: User,
    event: CalendarEvent,
    guild_id: int,
) -> None:
    """Notify a user they were added as an attendee on a calendar event."""
    if attendee.id == organizer.id:
        return
    organizer_name = handle_of(organizer)
    when = _format_event_when(event, attendee)
    locale = _recipient_locale(attendee)
    await _deliver_event_notification(
        session,
        recipient=attendee,
        notification_type=NotificationType.event_invitation,
        data=_event_data(event, guild_id, organizer_name=organizer_name),
        email_enabled=attendee.email_events is not False,
        push_enabled=attendee.push_events is not False,
        email_subject=email_t(
            "event.invitation.subject", locale, event=event.title, escape=False
        ),
        email_headline=email_t("event.invitation.title", locale),
        email_body=email_t(
            "event.invitation.body",
            locale,
            organizer=organizer_name,
            event=event.title,
            when=when,
        ),
        push_title=_nt("event.invitation.title", locale),
        push_body=_nt("event.invitation.body", locale, event=event.title, when=when),
    )


async def notify_event_updated(
    session: AsyncSession,
    *,
    attendee: User,
    editor: User,
    event: CalendarEvent,
    guild_id: int,
    time_changed: bool,
) -> None:
    """Notify an attendee that an event's details changed (or was rescheduled)."""
    if attendee.id == editor.id:
        return
    editor_name = handle_of(editor)
    when = _format_event_when(event, attendee)
    locale = _recipient_locale(attendee)
    key = "event.rescheduled" if time_changed else "event.updated"
    await _deliver_event_notification(
        session,
        recipient=attendee,
        notification_type=NotificationType.event_updated,
        data=_event_data(
            event, guild_id, editor_name=editor_name, time_changed=time_changed
        ),
        email_enabled=attendee.email_events is not False,
        push_enabled=attendee.push_events is not False,
        email_subject=email_t(
            f"{key}.subject", locale, event=event.title, escape=False
        ),
        email_headline=email_t(f"{key}.title", locale),
        email_body=email_t(
            f"{key}.body", locale, editor=editor_name, event=event.title, when=when
        ),
        push_title=_nt(f"{key}.title", locale),
        push_body=_nt(f"{key}.body", locale, event=event.title, when=when),
    )


async def notify_event_cancelled(
    session: AsyncSession,
    *,
    attendee: User,
    canceller: User,
    event: CalendarEvent,
    guild_id: int,
) -> None:
    """Notify an attendee that an event was cancelled (deleted)."""
    if attendee.id == canceller.id:
        return
    canceller_name = handle_of(canceller)
    when = _format_event_when(event, attendee)
    locale = _recipient_locale(attendee)
    await _deliver_event_notification(
        session,
        recipient=attendee,
        notification_type=NotificationType.event_cancelled,
        data=_event_data(event, guild_id, canceller_name=canceller_name),
        email_enabled=attendee.email_events is not False,
        push_enabled=attendee.push_events is not False,
        email_subject=email_t(
            "event.cancelled.subject", locale, event=event.title, escape=False
        ),
        email_headline=email_t("event.cancelled.title", locale),
        email_body=email_t(
            "event.cancelled.body",
            locale,
            canceller=canceller_name,
            event=event.title,
            when=when,
        ),
        push_title=_nt("event.cancelled.title", locale),
        push_body=_nt("event.cancelled.body", locale, event=event.title, when=when),
    )


async def notify_event_rsvp(
    session: AsyncSession,
    *,
    organizer: User,
    responder: User,
    event: CalendarEvent,
    rsvp_status: RSVPStatus,
    guild_id: int,
) -> None:
    """Notify the organizer that an attendee responded to their event."""
    if organizer.id == responder.id:
        return
    responder_name = handle_of(responder)
    status_value = (
        rsvp_status.value if isinstance(rsvp_status, RSVPStatus) else str(rsvp_status)
    )
    locale = _recipient_locale(organizer)
    await _deliver_event_notification(
        session,
        recipient=organizer,
        notification_type=NotificationType.event_rsvp,
        data=_event_data(
            event,
            guild_id,
            responder_name=responder_name,
            rsvp_status=status_value,
        ),
        email_enabled=organizer.email_events is not False,
        push_enabled=organizer.push_events is not False,
        email_subject=email_t(
            "event.rsvp.subject", locale, event=event.title, escape=False
        ),
        email_headline=email_t("event.rsvp.title", locale),
        email_body=email_t(
            "event.rsvp.body",
            locale,
            responder=responder_name,
            status=status_value,
            event=event.title,
        ),
        push_title=_nt("event.rsvp.title", locale),
        push_body=_nt(
            "event.rsvp.body",
            locale,
            responder=responder_name,
            status=status_value,
            event=event.title,
        ),
    )


async def notify_event_reminder(
    session: AsyncSession,
    *,
    recipient: User,
    event: CalendarEvent,
    guild_id: int,
) -> None:
    """Send a scheduled lead-time reminder for an upcoming event."""
    when = _format_event_when(event, recipient)
    locale = _recipient_locale(recipient)
    await _deliver_event_notification(
        session,
        recipient=recipient,
        notification_type=NotificationType.event_reminder,
        data=_event_data(event, guild_id),
        email_enabled=recipient.email_event_reminders is not False,
        push_enabled=recipient.push_event_reminders is not False,
        email_subject=email_t(
            "event.reminder.subject", locale, event=event.title, escape=False
        ),
        email_headline=email_t("event.reminder.title", locale),
        email_body=email_t("event.reminder.body", locale, event=event.title, when=when),
        push_title=_nt("event.reminder.title", locale),
        push_body=_nt("event.reminder.body", locale, event=event.title, when=when),
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
            title=_nt("task.assignment.title", locale),
            body=_nt(
                "task.assignment.body",
                locale,
                count=len(assignments),
                title=first.get("task_title") or "",
                project=first.get("project_name") or "",
            ),
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
    #: ``User`` attributes gating each channel. One queue backs both.
    email_pref: str
    push_pref: str
    #: What one queued row looks like to the senders, given the guild schema it
    #: was found in (which IS the row's guild).
    row: Callable[[object, int], dict]
    #: Send the batch. The push half returns ``(delivered, retry_worth_it)``.
    send_email: Callable[[AsyncSession, User, list[dict]], Awaitable[None]]
    send_push: Callable[[AsyncSession, User, list[dict]], Awaitable[tuple[bool, bool]]]
    #: ``User`` column recording when the last one went out, if any. A record,
    #: never a gate — the send window comes from the queue itself.
    stamp: str | None = None
    quiet_period: timedelta = ASSIGNMENT_QUIET_PERIOD
    max_window: timedelta = ASSIGNMENT_MAX_WINDOW


def wants_digest(email_pref: bool | None, push_pref: bool | None) -> bool:
    """Whether a user still wants a digest on either channel.

    One queue backs both, so it may only be discarded once neither is on —
    clearing it because the email was switched off would silently take the
    push with it.
    """
    return email_pref is not False or push_pref is not False


async def _run_digest_pass(
    session: AsyncSession, spec: DigestSpec, *, now: datetime
) -> None:
    """Send ``spec``'s digest to opted-in users as of ``now``.

    Each user's pending items live in their own guild schemas, so they are
    gathered with the user's membership context (not the guild's role) and
    marked processed back in each schema. Email and push ship together, on the
    same trigger, so the two channels tell the same story — see
    :func:`_digest_is_due` for the timing.
    """
    model = spec.model
    result = await session.exec(
        select(User).where(
            or_(
                getattr(User, spec.email_pref).is_not(False),
                getattr(User, spec.push_pref).is_not(False),
            )
        )
    )
    users = result.scalars().all()
    if not users:
        logger.debug("%s: no opted-in users", spec.name)
        return
    # Capture before routing — the gather expunges the identity map. The
    # channel preferences are deliberately NOT snapshotted here; they are read
    # off the freshly reloaded row at delivery time.
    candidates = [(u.id, u.email) for u in users]
    for user_id, email in candidates:
        per_guild_items: dict[int, list[int]] = {}
        queued_at: list[datetime] = []

        # Capture user_id / per_guild_items as defaults so this closure doesn't
        # bind the loop variables by reference (B023) — safe even if the call
        # site is ever refactored to defer the closures.
        async def _fetch(
            routed: AsyncSession,
            gid: int,
            *,
            _uid=user_id,
            _items=per_guild_items,
            _queued=queued_at,
        ) -> list[dict]:
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
            _queued.extend(item.created_at for item in items)
            return [spec.row(item, gid) for item in items]

        guild_ids = await member_guild_ids(session, user_id)
        # Digests act on membership (no live session exists here) — the
        # system sentinel clears the guild auth-policy gate.
        batch = await gather_across_guilds(
            session, user_id, guild_ids, _fetch, satisfied_providers=SYSTEM_SATISFIED
        )
        if not batch or not _digest_is_due(
            queued_at,
            now=now,
            quiet_period=spec.quiet_period,
            max_window=spec.max_window,
        ):
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
        if getattr(user, spec.email_pref) is not False:
            try:
                await spec.send_email(session, user, batch)
                delivered = True
                logger.info(
                    "%s: sent %d item(s) to user %s", spec.name, len(batch), email
                )
            except email_service.EmailNotConfiguredError:
                logger.warning(
                    "SMTP not configured; skipping %s for %s", spec.name, email
                )
            except RuntimeError as exc:  # pragma: no cover
                logger.error("Failed to send %s: %s", spec.name, exc)
                retry = True
        if getattr(user, spec.push_pref) is not False:
            pushed, push_retry = await spec.send_push(session, user, batch)
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
                email,
            )
        # Mark the gathered items processed, back in each guild's schema.
        for gid, item_ids in per_guild_items.items():
            if not item_ids:
                continue
            session.expunge_all()
            await set_rls_context(
                session,
                user_id=user_id,
                guild_id=gid,
                satisfied_providers=SYSTEM_SATISFIED,
            )
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
    guild_ids = (
        (
            await session.exec(
                select(Guild.id)
                .where(Guild.status == GuildStatus.active.value)
                .order_by(Guild.id.asc())
            )
        )
        .scalars()
        .all()
    )
    for guild_id in guild_ids:
        session.expunge_all()
        await set_rls_context(session, guild_id=guild_id, guild_role="admin")
        for model in models:
            await session.exec(delete(model).where(model.created_at < cutoff))
        await session.commit()


# --- Task assignment -------------------------------------------------------


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
    email_pref="email_task_assignment",
    push_pref="push_task_assignment",
    row=_assignment_row,
    send_email=lambda session, user, items: (
        email_service.send_task_assignment_digest_email(session, user, items)
    ),
    send_push=_send_assignment_push,
    stamp="last_task_assignment_digest_at",
)


async def _run_assignment_digest_pass(session: AsyncSession, *, now: datetime) -> None:
    """Send task-assignment digests. Split out from
    ``process_task_assignment_digests`` so tests can drive it with the test
    session."""
    await _run_digest_pass(session, ASSIGNMENT_DIGEST, now=now)


async def process_task_assignment_digests() -> None:
    async with AdminSessionLocal() as session:
        await _run_assignment_digest_pass(session, now=datetime.now(timezone.utc))


async def _run_assignment_gc_pass(session: AsyncSession, *, now: datetime) -> None:
    await _run_gc_pass(session, (TaskAssignmentDigestItem, ReactionDigestItem), now=now)


async def process_assignment_digest_gc() -> None:
    async with AdminSessionLocal() as session:
        await set_rls_context(session)
        await _run_assignment_gc_pass(session, now=datetime.now(timezone.utc))


# --- Reactions -------------------------------------------------------------


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


def _reaction_line(
    entries: Sequence[dict[str, Any]],
    *,
    count: int,
    reactor_ids: Sequence[int],
    context_title: str,
    target_path: str,
    smart_link: str | None,
    target_type: str,
    target_id: int,
    guild_id: int,
) -> dict[str, Any]:
    """One bell payload for every reaction rolled up so far.

    ``emoji`` / ``reactor_name`` / ``reactor_id`` keep naming the most recent
    one: a client that predates the rollup still renders a true sentence, and
    the newer client uses them as the reactor it names first. ``reactor_ids``
    is what the sentence counts, so it outlives the detail entries — a line
    whose oldest reactions have rolled off still knows how many people are in
    it.
    """
    latest = entries[-1] if entries else {}
    return {
        "target_type": target_type,
        "target_id": target_id,
        "context_title": context_title,
        "guild_id": guild_id,
        "target_path": target_path,
        "smart_link": smart_link,
        "emoji": latest.get("emoji"),
        "reactor_name": latest.get("reactor_name"),
        "reactor_id": latest.get("reactor_id"),
        "count": count,
        "reactor_count": len(reactor_ids),
        "reactor_ids": list(reactor_ids),
        "reactions": list(entries[-MAX_ROLLED_UP_REACTIONS:]),
    }


async def _lock_reaction_line(session: AsyncSession, key: str) -> None:
    """Serialize the read-then-write on one recipient's rolled-up line.

    Two people reacting to the same comment at the same moment would otherwise
    both find no line to join and write one each. Transaction-scoped, and keyed
    narrowly enough that only reactions aimed at the same line ever wait.
    """
    await session.exec(
        select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0)))
    )


async def enqueue_reaction_event(
    session: AsyncSession,
    *,
    author: User,
    reactor: User,
    reaction,
    context_title: str,
    target_path: str,
    guild_id: int,
) -> None:
    """Record that someone reacted to something ``author`` wrote.

    Reactions are the lightest signal in the app and they arrive in flurries,
    so every channel digests them — including the bell, which rolls them up per
    thing-reacted-to rather than listing one entry per tap. An unread line
    absorbs the next reaction to the same comment and returns to the top of the
    inbox; once read, the next reaction starts a fresh line. Email and push
    wait for the digest worker as before.
    """
    if author.id == reactor.id:
        return
    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    reactor_name = handle_of(reactor)
    entry = {
        "id": reaction.id,
        "emoji": reaction.emoji,
        "reactor_id": reactor.id,
        "reactor_name": reactor_name,
    }
    await _lock_reaction_line(
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
    previous: Mapping[str, Any] = (existing.data if existing else None) or {}
    roster = _rolled_up_reactor_ids(previous)
    if reactor.id not in roster:
        roster.append(cast(int, reactor.id))
    line = _reaction_line(
        _rolled_up_reactions(previous) + [entry],
        count=_rolled_up_count(previous) + 1,
        reactor_ids=roster,
        context_title=context_title,
        target_path=target_path,
        smart_link=smart_link,
        target_type=reaction.target_type,
        target_id=reaction.target_id,
        guild_id=guild_id,
    )
    if existing is None:
        await user_notifications.create_notification(
            session,
            user_id=author.id,
            notification_type=NotificationType.comment_reaction,
            data=line,
        )
    else:
        await user_notifications.refresh_notification(session, existing, data=line)
    if wants_digest(author.email_comment_reactions, author.push_comment_reactions):
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
    await _lock_reaction_line(
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
            context_title=previous.get("context_title") or "",
            target_path=previous.get("target_path") or MY_TASKS_TARGET_PATH,
            smart_link=previous.get("smart_link"),
            target_type=target_type,
            target_id=target_id,
            guild_id=guild_id,
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
            title=_nt("comment.reaction.title", locale),
            body=_nt(
                "comment.reaction.body",
                locale,
                count=len(reactions),
                actor=first.get("reactor_name") or "",
                emoji=first.get("emoji") or "",
                context=first.get("context_title") or "",
            ),
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
    email_pref="email_comment_reactions",
    push_pref="push_comment_reactions",
    row=_reaction_row,
    send_email=lambda session, user, items: email_service.send_reaction_digest_email(
        session, user, items
    ),
    send_push=_send_reaction_push,
)


async def _run_reaction_digest_pass(session: AsyncSession, *, now: datetime) -> None:
    """Send reaction digests. Split out from ``process_reaction_digests`` so
    tests can drive it with the test session."""
    await _run_digest_pass(session, REACTION_DIGEST, now=now)


async def process_reaction_digests() -> None:
    async with AdminSessionLocal() as session:
        await _run_reaction_digest_pass(session, now=datetime.now(timezone.utc))


def _resolve_timezone(value: str | None) -> ZoneInfo:
    zone_id = value or "UTC"
    try:
        return ZoneInfo(zone_id)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


async def _overdue_tasks_for_user(session: AsyncSession, user_id: int) -> list[dict]:
    """Overdue tasks assigned to the user *in the currently routed guild schema*.

    Run once per guild via ``gather_across_guilds`` (the session is routed into
    each of the user's guilds in turn), so it only ever sees one guild's rows.
    Template projects are excluded: their tasks are blueprints, not work, so a
    due date on one is never actually overdue. Archived projects and archived
    tasks are excluded for the same reason — archiving is how a user says the
    work is off their plate, so a past due date on one is not a deadline the
    digest should still be chasing. This matches the filters the cross-guild My
    Tasks list already applies.
    """
    stmt = (
        select(Task, Project.name, Project.id, Initiative.guild_id)
        .join(Project, Task.project_id == Project.id)
        .join(Initiative, Project.initiative_id == Initiative.id)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .join(TaskStatus, Task.task_status_id == TaskStatus.id)
        .where(
            TaskAssignee.user_id == user_id,
            Project.is_template.is_(False),
            Project.is_archived.is_(False),
            Task.is_archived.is_(False),
            Task.due_date.is_not(None),
            Task.due_date < datetime.now(timezone.utc),
            TaskStatus.category != TaskStatusCategory.done,
        )
        .order_by(Task.due_date.asc())
    )
    result = await session.exec(stmt)
    rows = result.all()
    tasks: list[dict] = []
    for row in rows:
        task, project_name, project_id, guild_id = row
        target_path = _task_target_path(task.id, project_id)
        tasks.append(
            {
                "title": task.title,
                "project_name": project_name,
                "due_date": task.due_date.strftime("%Y-%m-%d %H:%M UTC")
                if task.due_date
                else "N/A",
                "link": _build_smart_link(target_path=target_path, guild_id=guild_id),
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
            title=_nt("task.overdue.title", locale),
            body=_nt(
                "task.overdue.body",
                locale,
                count=len(tasks),
                title=tasks[0]["title"],
            ),
            data=data,
        )
    except Exception as exc:
        logger.error("Failed to send overdue push: %s", exc, exc_info=True)
        return False
    return sent > 0


async def _run_overdue_pass(session: AsyncSession, *, now: datetime) -> None:
    """Send overdue-task digests to opted-in users as of ``now``.

    Split out from ``process_overdue_notifications`` so tests can drive it with
    the test session (the worker opens its own ``AdminSessionLocal``). Each
    user's overdue tasks are gathered from their own guild schemas with their
    membership context — no all-guild access.

    Both channels ship from this one pass: the digest email and, for users with
    ``push_overdue_tasks`` on, a push notification. A user opted into either
    channel is a candidate, so turning email off doesn't silence push.
    """
    result = await session.exec(
        select(User).where(
            or_(
                User.email_overdue_tasks.is_(True),
                User.push_overdue_tasks.is_(True),
            )
        )
    )
    users = result.scalars().all()
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
            u.email,
            u.timezone,
            u.overdue_notification_time,
            u.last_overdue_notification_at,
        )
        for u in users
    ]
    for user_id, email, user_tz, notify_time, last_at in candidates:
        tz = _resolve_timezone(user_tz)
        now_local = now.astimezone(tz)
        try:
            hour, minute = map(int, notify_time.split(":"))
        except Exception:
            hour, minute = 21, 0
        target_local = now_local.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if now_local < target_local:
            continue
        if last_at and last_at.astimezone(tz).date() == now_local.date():
            continue
        # User-scoped: visit each of the user's guild schemas with their own
        # membership context (no all-guild access) and collect their overdue tasks.
        guild_ids = await member_guild_ids(session, user_id)
        tasks = await gather_across_guilds(
            session,
            user_id,
            guild_ids,
            # _uid default-binds user_id so the closure doesn't capture the loop
            # variable by reference (B023).
            lambda routed, _gid, _uid=user_id: _overdue_tasks_for_user(routed, _uid),
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
        if user.email_overdue_tasks:
            try:
                await email_service.send_overdue_tasks_email(session, user, tasks)
                delivered = True
                logger.info(
                    "overdue-digest: sent %d overdue task(s) to user %s",
                    len(tasks),
                    email,
                )
            except email_service.EmailNotConfiguredError:
                logger.warning(
                    "SMTP not configured; skipping overdue digest for %s", email
                )
            except RuntimeError as exc:  # pragma: no cover
                logger.error("Failed to send overdue digest: %s", exc)
        if user.push_overdue_tasks:
            delivered = await _send_overdue_push(session, user, tasks) or delivered
        if not delivered:
            continue
        user.last_overdue_notification_at = now
        session.add(user)
        await session.commit()


async def process_overdue_notifications() -> None:
    async with AdminSessionLocal() as session:
        await _run_overdue_pass(session, now=datetime.now(timezone.utc))


async def _run_event_reminder_pass(session: AsyncSession, *, now: datetime) -> None:
    """Dispatch any reminders due as of ``now``.

    User-scoped: for each user who enabled reminders, visit their own guild
    schemas with their membership context (no superadmin) and dispatch reminders
    for the events they attend there. Split out from ``process_event_reminders``
    so tests can drive it with the test session.
    """
    horizon = now + timedelta(days=1)
    # Allow events that started within the grace window so a 0-minute
    # ("at the time of the event") reminder still fires on the next poll.
    lower = now - EVENT_REMINDER_GRACE
    # Asked of the system engine, not of this session: the sweep routes into
    # each guild's schema in turn, and a routed session cannot read an
    # account's preferences.
    users = await accounts_service.load_event_reminder_optins()
    candidates = [(u.id, u.event_reminder_minutes_before) for u in users]
    for user_id, minutes in candidates:
        if minutes is None:
            continue
        for guild_id in await member_guild_ids(session, user_id):
            session.expunge_all()
            await set_rls_context(
                session,
                user_id=user_id,
                guild_id=guild_id,
                satisfied_providers=SYSTEM_SATISFIED,
            )
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
                (e.id, e.start_at, e.guild_id)
                for e in events
                if e.start_at - timedelta(minutes=minutes) <= now
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
    async with AdminSessionLocal() as session:
        await _run_event_reminder_pass(session, now=datetime.now(timezone.utc))


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
        data={"target_path": "/settings/profile"},
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
            "target_path": "/settings/profile",
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
        data={"reason": reason, "target_path": "/settings/profile"},
    )


async def queue_account_unsuspended(session: AsyncSession, *, user: User) -> None:
    """Tell a user their account is theirs again."""
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.account_unsuspended,
        data={"target_path": "/"},
    )
