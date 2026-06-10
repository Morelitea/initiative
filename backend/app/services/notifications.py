from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, delete, update as sa_update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import AdminSessionLocal, reapply_rls_context, set_rls_context
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.core.config import settings as app_config
from app.models.initiative import Initiative
from app.models.project import Project
from app.models.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory
from app.models.task_assignment_digest import TaskAssignmentDigestItem
from app.models.calendar_event import CalendarEvent, CalendarEventAttendee, RSVPStatus
from app.models.event_reminder_dispatch import EventReminderDispatch
from app.core.capabilities import Capability, roles_with_capability
from app.models.user import User, UserStatus
from app.models.notification import NotificationType
from app.services import email as email_service
from app.services import user_notifications
from app.services import push_notifications

logger = logging.getLogger(__name__)

DIGEST_POLL_SECONDS = 120
OVERDUE_POLL_SECONDS = 300
EVENT_REMINDER_POLL_SECONDS = 60
# Events that started within this window are still eligible, so a 0-minute
# ("at start") reminder fires on the next poll rather than being missed.
EVENT_REMINDER_GRACE = timedelta(minutes=5)


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


def _task_target_path(task_id: int | None, project_id: int | None) -> str:
    if task_id:
        return f"/tasks/{task_id}"
    if project_id:
        return f"/projects/{project_id}"
    return "/projects"


def _project_target_path(project_id: int | None) -> str:
    if project_id is None:
        return "/projects"
    return f"/projects/{project_id}"


def _event_target_path(event_id: int | None) -> str:
    if event_id is None:
        return "/calendar"
    return f"/events/{event_id}"


def _initiative_target_path(initiative_id: int | None) -> str:
    if initiative_id is None:
        return "/initiatives"
    return f"/initiatives/{initiative_id}"


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
            "assigned_by_name": assigned_by.full_name or assigned_by.email,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": smart_link,
        },
    )
    # Email: enqueue digest if email preference enabled
    if assignee.email_task_assignment is not False:
        event = TaskAssignmentDigestItem(
            user_id=assignee.id,
            task_id=task.id,
            project_id=task.project_id,
            task_title=task.title,
            project_name=project_name,
            assigned_by_name=assigned_by.full_name or assigned_by.email,
            assigned_by_id=assigned_by.id,
        )
        session.add(event)
    # Push notification
    if assignee.push_task_assignment is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=assignee.id,
                notification_type=NotificationType.task_assignment,
                title="New Task Assignment",
                body=f"{task.title} in {project_name}",
                data={
                    "type": "task_assignment",
                    "task_id": str(task.id),
                    "guild_id": str(guild_id),
                    "target_path": target_path,
                },
            )
        except Exception as exc:
            logger.error(f"Failed to send push notification: {exc}", exc_info=True)


async def clear_task_assignment_queue_for_user(session: AsyncSession, user_id: int) -> None:
    stmt = delete(TaskAssignmentDigestItem).where(
        TaskAssignmentDigestItem.user_id == user_id,
        TaskAssignmentDigestItem.processed_at.is_(None),
    )
    await session.exec(stmt)


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
            await email_service.send_initiative_added_email(session, user, initiative_name)
        except email_service.EmailNotConfiguredError:
            logger.warning("SMTP not configured; skipping initiative notification for %s", user.email)
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send initiative notification: %s", exc)
    # Push notification
    if user.push_initiative_addition is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=user.id,
                notification_type=NotificationType.initiative_added,
                title="Added to Initiative",
                body=f"You've been added to {initiative_name}",
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
            logger.warning("SMTP not configured; skipping project notification for %s", user.email)
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send project notification: %s", exc)
    # Push notification
    if user.push_project_added is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=user.id,
                notification_type=NotificationType.project_added,
                title="New Project Added",
                body=f"{project_name} in {initiative_name}",
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


async def notify_admins_pending_user(session: AsyncSession, pending_user: User) -> None:
    manager_roles = list(roles_with_capability(Capability.USERS_MANAGE))
    stmt = select(User).where(User.role.in_(manager_roles), User.status == UserStatus.active)
    result = await session.exec(stmt)
    admins = result.scalars().all()
    if not admins:
        return
    for admin in admins:
        await user_notifications.create_notification(
            session,
            user_id=admin.id,
            notification_type=NotificationType.user_pending_approval,
            data={"user_id": pending_user.id, "email": pending_user.email},
        )
    await session.commit()


async def notify_document_mention(
    session: AsyncSession,
    *,
    mentioned_user: User,
    mentioned_by: User,
    document_id: int,
    document_title: str,
    guild_id: int,
) -> None:
    """Notify a user they were mentioned in a document."""
    if mentioned_user.id == mentioned_by.id:
        return
    target_path = f"/documents/{document_id}"
    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    mentioned_by_name = mentioned_by.full_name or mentioned_by.email
    # Always create in-app notification
    await user_notifications.create_notification(
        session,
        user_id=mentioned_user.id,
        notification_type=NotificationType.mention,
        data={
            "document_id": document_id,
            "document_title": document_title,
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
                subject=f"You were mentioned in {document_title}",
                headline="You were mentioned",
                body_text=f"{mentioned_by_name} mentioned you in {document_title}",
                link=smart_link,
            )
        except email_service.EmailNotConfiguredError:
            logger.warning("SMTP not configured; skipping mention email for %s", mentioned_user.email)
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send mention email: %s", exc)
    # Push notification
    if getattr(mentioned_user, "push_mentions", True) is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=mentioned_user.id,
                notification_type=NotificationType.mention,
                title="You were mentioned",
                body=f"{mentioned_by_name} mentioned you in {document_title}",
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
) -> None:
    """Notify a user they were mentioned in a comment."""
    if mentioned_user.id == mentioned_by.id:
        return

    if task_id:
        target_path = f"/tasks/{task_id}"
    elif document_id:
        target_path = f"/documents/{document_id}"
    else:
        return

    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    mentioned_by_name = mentioned_by.full_name or mentioned_by.email

    # Always create in-app notification
    await user_notifications.create_notification(
        session,
        user_id=mentioned_user.id,
        notification_type=NotificationType.mention,
        data={
            "comment_id": comment_id,
            "task_id": task_id,
            "document_id": document_id,
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
                subject="You were mentioned in a comment",
                headline="You were mentioned",
                body_text=f"{mentioned_by_name} mentioned you in a comment on {context_title}",
                link=smart_link,
            )
        except email_service.EmailNotConfiguredError:
            logger.warning("SMTP not configured; skipping mention email for %s", mentioned_user.email)
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send mention email: %s", exc)
    # Push notification
    if getattr(mentioned_user, "push_mentions", True) is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=mentioned_user.id,
                notification_type=NotificationType.mention,
                title="You were mentioned",
                body=f"{mentioned_by_name} mentioned you in a comment on {context_title}",
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
) -> None:
    """Notify task assignee that their task was mentioned in a comment."""
    if assignee.id == mentioned_by.id:
        return

    if context_task_id:
        target_path = f"/tasks/{context_task_id}"
    elif context_document_id:
        target_path = f"/documents/{context_document_id}"
    else:
        return

    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    mentioned_by_name = mentioned_by.full_name or mentioned_by.email

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
                subject="Your task was mentioned",
                headline="Your task was mentioned",
                body_text=f"{mentioned_by_name} mentioned {mentioned_task_title} in {context_title}",
                link=smart_link,
            )
        except email_service.EmailNotConfiguredError:
            logger.warning("SMTP not configured; skipping mention email for %s", assignee.email)
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send mention email: %s", exc)
    # Push notification
    if getattr(assignee, "push_mentions", True) is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=assignee.id,
                notification_type=NotificationType.mention,
                title="Your task was mentioned",
                body=f"{mentioned_by_name} mentioned {mentioned_task_title} in {context_title}",
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

    target_path = f"/tasks/{task_id}"
    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    commenter_name = commenter.full_name or commenter.email

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
                subject=f"New comment on {task_title}",
                headline="New comment on your task",
                body_text=f"{commenter_name} commented on {task_title}",
                link=smart_link,
            )
        except email_service.EmailNotConfiguredError:
            logger.warning("SMTP not configured; skipping comment email for %s", assignee.email)
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send comment email: %s", exc)
    # Push notification
    if getattr(assignee, "push_mentions", True) is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=assignee.id,
                notification_type=NotificationType.comment_on_task,
                title="New comment on your task",
                body=f"{commenter_name} commented on {task_title}",
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


async def notify_comment_on_document(
    session: AsyncSession,
    *,
    author: User,
    commenter: User,
    comment_id: int,
    document_id: int,
    document_title: str,
    guild_id: int,
) -> None:
    """Notify document author that someone commented on their document."""
    if author.id == commenter.id:
        return

    target_path = f"/documents/{document_id}"
    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    commenter_name = commenter.full_name or commenter.email

    # Always create in-app notification
    await user_notifications.create_notification(
        session,
        user_id=author.id,
        notification_type=NotificationType.comment_on_document,
        data={
            "comment_id": comment_id,
            "document_id": document_id,
            "document_title": document_title,
            "commenter_name": commenter_name,
            "commenter_id": commenter.id,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": smart_link,
        },
    )
    # Email
    if getattr(author, "email_mentions", True) is not False:
        try:
            await email_service.send_mention_email(
                session,
                author,
                subject=f"New comment on {document_title}",
                headline="New comment on your document",
                body_text=f"{commenter_name} commented on {document_title}",
                link=smart_link,
            )
        except email_service.EmailNotConfiguredError:
            logger.warning("SMTP not configured; skipping comment email for %s", author.email)
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send comment email: %s", exc)
    # Push notification
    if getattr(author, "push_mentions", True) is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=author.id,
                notification_type=NotificationType.comment_on_document,
                title="New comment on your document",
                body=f"{commenter_name} commented on {document_title}",
                data={
                    "type": "comment_on_document",
                    "comment_id": str(comment_id),
                    "document_id": str(document_id),
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
) -> None:
    """Notify parent comment author that someone replied to their comment."""
    if parent_author.id == replier.id:
        return

    if task_id:
        target_path = f"/tasks/{task_id}"
    elif document_id:
        target_path = f"/documents/{document_id}"
    else:
        return

    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    replier_name = replier.full_name or replier.email

    # Always create in-app notification
    await user_notifications.create_notification(
        session,
        user_id=parent_author.id,
        notification_type=NotificationType.comment_reply,
        data={
            "comment_id": comment_id,
            "task_id": task_id,
            "document_id": document_id,
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
                subject="Reply to your comment",
                headline="Reply to your comment",
                body_text=f"{replier_name} replied to your comment on {context_title}",
                link=smart_link,
            )
        except email_service.EmailNotConfiguredError:
            logger.warning("SMTP not configured; skipping reply email for %s", parent_author.email)
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send reply email: %s", exc)
    # Push notification
    if getattr(parent_author, "push_mentions", True) is not False:
        try:
            await push_notifications.send_push_to_user(
                session=session,
                user_id=parent_author.id,
                notification_type=NotificationType.comment_reply,
                title="Reply to your comment",
                body=f"{replier_name} replied to your comment on {context_title}",
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
    target_path = data.get("target_path", "/calendar")
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
            logger.warning("SMTP not configured; skipping event email for %s", recipient.email)
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
    organizer_name = organizer.full_name or organizer.email
    when = _format_event_when(event, attendee)
    await _deliver_event_notification(
        session,
        recipient=attendee,
        notification_type=NotificationType.event_invitation,
        data=_event_data(event, guild_id, organizer_name=organizer_name),
        email_enabled=attendee.email_events is not False,
        push_enabled=attendee.push_events is not False,
        email_subject=f"You're invited: {event.title}",
        email_headline="New event invitation",
        email_body=f"{organizer_name} invited you to {event.title} ({when}).",
        push_title="New event invitation",
        push_body=f"{event.title} ({when})",
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
    editor_name = editor.full_name or editor.email
    when = _format_event_when(event, attendee)
    if time_changed:
        headline = "Event rescheduled"
        body = f"{editor_name} rescheduled {event.title} to {when}."
    else:
        headline = "Event updated"
        body = f"{editor_name} updated {event.title} ({when})."
    await _deliver_event_notification(
        session,
        recipient=attendee,
        notification_type=NotificationType.event_updated,
        data=_event_data(
            event, guild_id, editor_name=editor_name, time_changed=time_changed
        ),
        email_enabled=attendee.email_events is not False,
        push_enabled=attendee.push_events is not False,
        email_subject=f"{headline}: {event.title}",
        email_headline=headline,
        email_body=body,
        push_title=headline,
        push_body=f"{event.title} ({when})",
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
    canceller_name = canceller.full_name or canceller.email
    when = _format_event_when(event, attendee)
    await _deliver_event_notification(
        session,
        recipient=attendee,
        notification_type=NotificationType.event_cancelled,
        data=_event_data(event, guild_id, canceller_name=canceller_name),
        email_enabled=attendee.email_events is not False,
        push_enabled=attendee.push_events is not False,
        email_subject=f"Event cancelled: {event.title}",
        email_headline="Event cancelled",
        email_body=f"{canceller_name} cancelled {event.title} ({when}).",
        push_title="Event cancelled",
        push_body=f"{event.title} ({when})",
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
    responder_name = responder.full_name or responder.email
    status_value = rsvp_status.value if isinstance(rsvp_status, RSVPStatus) else str(rsvp_status)
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
        email_subject=f"RSVP update: {event.title}",
        email_headline="RSVP update",
        email_body=f"{responder_name} responded “{status_value}” to {event.title}.",
        push_title="RSVP update",
        push_body=f"{responder_name} responded {status_value} to {event.title}",
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
    await _deliver_event_notification(
        session,
        recipient=recipient,
        notification_type=NotificationType.event_reminder,
        data=_event_data(event, guild_id),
        email_enabled=recipient.email_event_reminders is not False,
        push_enabled=recipient.push_event_reminders is not False,
        email_subject=f"Reminder: {event.title}",
        email_headline="Upcoming event",
        email_body=f"{event.title} starts at {when}.",
        push_title="Upcoming event",
        push_body=f"{event.title} ({when})",
    )


async def _run_assignment_digest_pass(session: AsyncSession, *, now: datetime) -> None:
    """Send task-assignment digests to opted-in users as of ``now``.

    Split out from ``process_task_assignment_digests`` so tests can drive it with
    the test session. Each user's pending digest items live in their own guild
    schemas, so they're gathered with the user's membership context (no
    superadmin) and the items are marked processed back in each schema.
    """
    result = await session.exec(select(User).where(User.email_task_assignment.is_not(False)))
    users = result.scalars().all()
    if not users:
        logger.debug("task-digest: no opted-in users")
        return
    # Capture before routing — the gather expunges the identity map.
    candidates = [(u.id, u.email, u.last_task_assignment_digest_at) for u in users]
    for user_id, email, last_at in candidates:
        if last_at and last_at + timedelta(hours=1) > now:
            continue  # rate-limited to one digest per hour
        per_guild_items: dict[int, list[int]] = {}

        # Capture user_id / per_guild_items as defaults so this closure doesn't
        # bind the loop variables by reference (B023) — safe even if the call
        # site is ever refactored to defer the closures.
        async def _fetch(routed: AsyncSession, gid: int, *, _uid=user_id, _items=per_guild_items) -> list[dict]:
            items = (
                await routed.exec(
                    select(TaskAssignmentDigestItem)
                    .where(
                        TaskAssignmentDigestItem.user_id == _uid,
                        TaskAssignmentDigestItem.processed_at.is_(None),
                    )
                    .order_by(TaskAssignmentDigestItem.created_at.asc())
                )
            ).scalars().all()
            _items[gid] = [item.id for item in items]
            return [
                {
                    "task_title": item.task_title,
                    "project_name": item.project_name,
                    "assigned_by_name": item.assigned_by_name,
                    "link": _build_smart_link(
                        target_path=_task_target_path(item.task_id, item.project_id),
                        guild_id=gid,  # the item's guild IS the routed schema
                    ),
                }
                for item in items
            ]

        guild_ids = await member_guild_ids(session, user_id)
        assignments = await gather_across_guilds(session, user_id, guild_ids, _fetch)
        if not assignments:
            continue
        # Send: re-load the user (gather expunged it) in a shared-table context.
        session.expunge_all()
        await set_rls_context(session, user_id=user_id)
        user = (await session.exec(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:  # deleted between the snapshot and now — skip, don't abort the pass
            continue
        try:
            await email_service.send_task_assignment_digest_email(session, user, assignments)
            logger.info("task-digest: sent %d assignment(s) to user %s", len(assignments), email)
        except email_service.EmailNotConfiguredError:
            logger.warning("SMTP not configured; skipping task digest for %s", email)
            continue
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send task digest: %s", exc)
            continue
        # Mark the gathered items processed, back in each guild's schema.
        for gid, item_ids in per_guild_items.items():
            if not item_ids:
                continue
            session.expunge_all()
            await set_rls_context(session, user_id=user_id, guild_id=gid)
            await session.exec(
                sa_update(TaskAssignmentDigestItem)
                .where(TaskAssignmentDigestItem.id.in_(item_ids))
                .values(processed_at=now)
            )
            await session.commit()
            await reapply_rls_context(session)  # commit may have dropped the connection's context
        session.expunge_all()
        await set_rls_context(session, user_id=user_id)
        user = (await session.exec(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            continue
        user.last_task_assignment_digest_at = now
        session.add(user)
        await session.commit()


async def process_task_assignment_digests() -> None:
    async with AdminSessionLocal() as session:
        await _run_assignment_digest_pass(session, now=datetime.now(timezone.utc))


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
    """
    stmt = (
        select(Task, Project.name, Project.id, Initiative.guild_id)
        .join(Project, Task.project_id == Project.id)
        .join(Initiative, Project.initiative_id == Initiative.id)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .join(TaskStatus, Task.task_status_id == TaskStatus.id)
        .where(
            TaskAssignee.user_id == user_id,
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
                "due_date": task.due_date.strftime("%Y-%m-%d %H:%M UTC") if task.due_date else "N/A",
                "link": _build_smart_link(target_path=target_path, guild_id=guild_id),
            }
        )
    return tasks


async def _run_overdue_pass(session: AsyncSession, *, now: datetime) -> None:
    """Send overdue-task digests to opted-in users as of ``now``.

    Split out from ``process_overdue_notifications`` so tests can drive it with
    the test session (the worker opens its own ``AdminSessionLocal``). Each
    user's overdue tasks are gathered from their own guild schemas with their
    membership context — no superadmin / all-guild access.
    """
    result = await session.exec(select(User).where(User.email_overdue_tasks.is_(True)))
    users = result.scalars().all()
    if not users:
        logger.debug("overdue-digest: no users opted in")
        return
    # Capture plain fields up front: gathering routes per guild and expunges the
    # identity map, which would detach these ORM rows.
    candidates = [
        (u.id, u.email, u.timezone, u.overdue_notification_time, u.last_overdue_notification_at)
        for u in users
    ]
    for user_id, email, user_tz, notify_time, last_at in candidates:
        tz = _resolve_timezone(user_tz)
        now_local = now.astimezone(tz)
        try:
            hour, minute = map(int, notify_time.split(":"))
        except Exception:
            hour, minute = 21, 0
        target_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_local < target_local:
            continue
        if last_at and last_at.astimezone(tz).date() == now_local.date():
            continue
        # User-scoped: visit each of the user's guild schemas with their own
        # membership context (no superadmin) and collect their overdue tasks.
        guild_ids = await member_guild_ids(session, user_id)
        tasks = await gather_across_guilds(
            session, user_id, guild_ids,
            # _uid default-binds user_id so the closure doesn't capture the loop
            # variable by reference (B023).
            lambda routed, _gid, _uid=user_id: _overdue_tasks_for_user(routed, _uid),
        )
        if not tasks:
            continue
        # Re-load the user (the gather expunged it) to send + stamp it. The
        # email/stamp touch only shared tables, so the user-only context is fine.
        session.expunge_all()
        await set_rls_context(session, user_id=user_id)
        user = (await session.exec(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:  # deleted between the snapshot and now — skip, don't abort the pass
            continue
        try:
            await email_service.send_overdue_tasks_email(session, user, tasks)
            logger.info("overdue-digest: sent %d overdue task(s) to user %s", len(tasks), email)
        except email_service.EmailNotConfiguredError:
            logger.warning("SMTP not configured; skipping overdue digest for %s", email)
            continue
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send overdue digest: %s", exc)
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
    users = (
        await session.exec(select(User).where(User.event_reminder_minutes_before.is_not(None)))
    ).scalars().all()
    candidates = [(u.id, u.event_reminder_minutes_before) for u in users]
    for user_id, minutes in candidates:
        if minutes is None:
            continue
        for guild_id in await member_guild_ids(session, user_id):
            session.expunge_all()
            await set_rls_context(session, user_id=user_id, guild_id=guild_id)
            events = (
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
            ).scalars().all()
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
                await reapply_rls_context(session)
                recipient = (
                    await session.exec(select(User).where(User.id == user_id))
                ).scalar_one_or_none()
                event = (
                    await session.exec(select(CalendarEvent).where(CalendarEvent.id == event_id))
                ).scalar_one_or_none()
                if recipient is None or event is None:
                    continue  # deleted mid-run; dedup row stays so we don't retry
                await notify_event_reminder(
                    session, recipient=recipient, event=event, guild_id=ev_guild_id
                )
                await session.commit()
                await reapply_rls_context(session)


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


