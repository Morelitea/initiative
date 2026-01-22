from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import AsyncSessionLocal
from app.core.config import settings as app_config
from app.models.initiative import Initiative
from app.models.project import Project
from app.models.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory
from app.models.task_assignment_digest import TaskAssignmentDigestItem
from app.models.user import User, UserRole
from app.models.notification import NotificationType
from app.services import email as email_service
from app.services import user_notifications
from app.services import push_notifications

logger = logging.getLogger(__name__)

DIGEST_POLL_SECONDS = 120
OVERDUE_POLL_SECONDS = 300


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


async def _project_guild_map(session: AsyncSession, project_ids: set[int]) -> dict[int, int]:
    if not project_ids:
        return {}
    stmt = (
        select(Project.id, Initiative.guild_id)
        .join(Project.initiative)
        .where(Project.id.in_(tuple(project_ids)))
    )
    result = await session.exec(stmt)
    rows = result.all()
    mapping: dict[int, int] = {}
    for project_id, guild_id in rows:
        if project_id is not None and guild_id is not None:
            mapping[int(project_id)] = int(guild_id)
    return mapping


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
    if assignee.notify_task_assignment is False:
        return
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
    target_path = _task_target_path(task.id, task.project_id)
    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
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
    # Send push notification
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
) -> None:
    if user.notify_initiative_addition is False:
        return
    try:
        await email_service.send_initiative_added_email(session, user, initiative_name)
    except email_service.EmailNotConfiguredError:
        logger.warning("SMTP not configured; skipping initiative notification for %s", user.email)
    except RuntimeError as exc:  # pragma: no cover
        logger.error("Failed to send initiative notification: %s", exc)
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.initiative_added,
        data={"initiative_id": initiative_id, "initiative_name": initiative_name},
    )
    # Send push notification
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
                "target_path": f"/initiatives/{initiative_id}",
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
    if user.notify_project_added is False:
        return
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
    target_path = _project_target_path(project_id)
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
    # Send push notification
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
    stmt = select(User).where(User.role == UserRole.admin, User.is_active.is_(True))
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
    if getattr(mentioned_user, "notify_mentions", True) is False:
        return
    target_path = f"/documents/{document_id}"
    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    await user_notifications.create_notification(
        session,
        user_id=mentioned_user.id,
        notification_type=NotificationType.mention,
        data={
            "document_id": document_id,
            "document_title": document_title,
            "mentioned_by_name": mentioned_by.full_name or mentioned_by.email,
            "mentioned_by_id": mentioned_by.id,
            "guild_id": guild_id,
            "target_path": target_path,
            "smart_link": smart_link,
        },
    )
    # Send push notification
    try:
        mentioned_by_name = mentioned_by.full_name or mentioned_by.email
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
    if getattr(mentioned_user, "notify_mentions", True) is False:
        return

    if task_id:
        target_path = f"/tasks/{task_id}"
    elif document_id:
        target_path = f"/documents/{document_id}"
    else:
        return

    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    mentioned_by_name = mentioned_by.full_name or mentioned_by.email

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
    if getattr(assignee, "notify_mentions", True) is False:
        return

    if context_task_id:
        target_path = f"/tasks/{context_task_id}"
    elif context_document_id:
        target_path = f"/documents/{context_document_id}"
    else:
        return

    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    mentioned_by_name = mentioned_by.full_name or mentioned_by.email

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
    if getattr(assignee, "notify_mentions", True) is False:
        return

    target_path = f"/tasks/{task_id}"
    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    commenter_name = commenter.full_name or commenter.email

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
    if getattr(author, "notify_mentions", True) is False:
        return

    target_path = f"/documents/{document_id}"
    smart_link = _build_smart_link(target_path=target_path, guild_id=guild_id)
    commenter_name = commenter.full_name or commenter.email

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


async def _pending_assignment_user_ids(session: AsyncSession) -> list[int]:
    stmt = (
        select(TaskAssignmentDigestItem.user_id)
        .where(TaskAssignmentDigestItem.processed_at.is_(None))
        .distinct()
    )
    result = await session.exec(stmt)
    return result.scalars().all()


async def _load_user(session: AsyncSession, user_id: int) -> User | None:
    result = await session.exec(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def process_task_assignment_digests() -> None:
    async with AsyncSessionLocal() as session:
        user_ids = await _pending_assignment_user_ids(session)
        if not user_ids:
            logger.debug("task-digest: no pending assignment events")
            return
        logger.debug("task-digest: processing %d user(s)", len(user_ids))
        now = datetime.now(timezone.utc)
        for user_id in user_ids:
            user = await _load_user(session, int(user_id))
            if not user or user.notify_task_assignment is False:
                await clear_task_assignment_queue_for_user(session, user_id)
                await session.commit()
                continue
            events_stmt = (
                select(TaskAssignmentDigestItem)
                .where(
                    TaskAssignmentDigestItem.user_id == user_id,
                    TaskAssignmentDigestItem.processed_at.is_(None),
                )
                .order_by(TaskAssignmentDigestItem.created_at.asc())
            )
            events_result = await session.exec(events_stmt)
            events = events_result.scalars().all()
            if not events:
                continue
            if user.last_task_assignment_digest_at and user.last_task_assignment_digest_at + timedelta(hours=1) > now:
                continue
            project_ids = {event.project_id for event in events if event.project_id is not None}
            guild_map = await _project_guild_map(session, project_ids)
            assignments = []
            for event in events:
                target_path = _task_target_path(event.task_id, event.project_id)
                assignments.append(
                    {
                        "task_title": event.task_title,
                        "project_name": event.project_name,
                        "assigned_by_name": event.assigned_by_name,
                        "link": _build_smart_link(
                            target_path=target_path,
                            guild_id=guild_map.get(event.project_id),
                        ),
                    }
                )
            try:
                await email_service.send_task_assignment_digest_email(session, user, assignments)
                logger.info(
                    "task-digest: sent %d assignment(s) to user %s",
                    len(assignments),
                    user.email,
                )
            except email_service.EmailNotConfiguredError:
                logger.warning("SMTP not configured; skipping task digest for %s", user.email)
                continue
            except RuntimeError as exc:  # pragma: no cover
                logger.error("Failed to send task digest: %s", exc)
                continue
            for event in events:
                event.processed_at = now
                session.add(event)
            user.last_task_assignment_digest_at = now
            session.add(user)
            await session.commit()


def _resolve_timezone(value: str | None) -> ZoneInfo:
    zone_id = value or "UTC"
    try:
        return ZoneInfo(zone_id)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


async def _overdue_tasks_for_user(session: AsyncSession, user: User) -> list[dict]:
    stmt = (
        select(Task, Project.name, Project.id, Initiative.guild_id)
        .join(Project, Task.project_id == Project.id)
        .join(Initiative, Project.initiative_id == Initiative.id)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .join(TaskStatus, Task.task_status_id == TaskStatus.id)
        .where(
            TaskAssignee.user_id == user.id,
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


async def process_overdue_notifications() -> None:
    async with AsyncSessionLocal() as session:
        stmt = select(User).where(User.notify_overdue_tasks.is_(True))
        result = await session.exec(stmt)
        users = result.scalars().all()
        if not users:
            logger.debug("overdue-digest: no users opted in")
            return
        now_utc = datetime.now(timezone.utc)
        for user in users:
            tz = _resolve_timezone(user.timezone)
            now_local = now_utc.astimezone(tz)
            try:
                hour, minute = map(int, user.overdue_notification_time.split(":"))
            except Exception:
                hour, minute = 21, 0
            target_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now_local < target_local:
                continue
            if user.last_overdue_notification_at:
                last_local = user.last_overdue_notification_at.astimezone(tz)
                if last_local.date() == now_local.date():
                    continue
            tasks = await _overdue_tasks_for_user(session, user)
            if not tasks:
                continue
            try:
                await email_service.send_overdue_tasks_email(session, user, tasks)
                logger.info("overdue-digest: sent %d overdue task(s) to user %s", len(tasks), user.email)
            except email_service.EmailNotConfiguredError:
                logger.warning("SMTP not configured; skipping overdue digest for %s", user.email)
                continue
            except RuntimeError as exc:  # pragma: no cover
                logger.error("Failed to send overdue digest: %s", exc)
                continue
            user.last_overdue_notification_at = now_utc
            session.add(user)
            await session.commit()


async def _loop_worker(task_coro, interval: int, name: str) -> None:
    logger.info("%s worker started (interval=%ss)", name, interval)
    try:
        while True:
            try:
                await task_coro()
            except Exception:  # pragma: no cover
                logger.exception("%s worker encountered an error", name)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:  # pragma: no cover
        logger.info("%s worker cancelled", name)
        raise


def start_background_tasks() -> list[asyncio.Task]:
    return [
        asyncio.create_task(
            _loop_worker(process_task_assignment_digests, DIGEST_POLL_SECONDS, "task-digest")
        ),
        asyncio.create_task(
            _loop_worker(process_overdue_notifications, OVERDUE_POLL_SECONDS, "overdue-digest")
        ),
    ]
