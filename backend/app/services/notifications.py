from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.project import Project
from app.models.task import Task, TaskAssignee, TaskStatus
from app.models.task_assignment_digest import TaskAssignmentDigestItem
from app.models.user import User, UserRole
from app.models.notification import NotificationType
from app.services import email as email_service
from app.services import user_notifications

logger = logging.getLogger(__name__)

DIGEST_POLL_SECONDS = 120
OVERDUE_POLL_SECONDS = 300


async def enqueue_task_assignment_event(
    session: AsyncSession,
    *,
    task: Task,
    assignee: User,
    assigned_by: User,
    project_name: str,
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
        },
    )


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
    await session.commit()


async def notify_project_added(
    session: AsyncSession,
    user: User,
    *,
    initiative_name: str,
    project_name: str,
    project_id: int,
    initiative_id: int,
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
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.project_added,
        data={
            "initiative_id": initiative_id,
            "initiative_name": initiative_name,
            "project_id": project_id,
            "project_name": project_name,
        },
    )
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
            assignments = [
                {
                    "task_title": event.task_title,
                    "project_name": event.project_name,
                    "assigned_by_name": event.assigned_by_name,
                }
                for event in events
            ]
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
        select(Task, Project.name)
        .join(Project, Task.project_id == Project.id)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .where(
            TaskAssignee.user_id == user.id,
            Task.due_date.is_not(None),
            Task.due_date < datetime.now(timezone.utc),
            Task.status != TaskStatus.done,
        )
        .order_by(Task.due_date.asc())
    )
    result = await session.exec(stmt)
    rows = result.all()
    tasks: list[dict] = []
    for row in rows:
        task, project_name = row
        tasks.append(
            {
                "title": task.title,
                "project_name": project_name,
                "due_date": task.due_date.strftime("%Y-%m-%d %H:%M UTC") if task.due_date else "N/A",
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
