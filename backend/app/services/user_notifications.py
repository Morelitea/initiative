from datetime import datetime, timezone
from typing import Mapping

from sqlalchemy import func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import reapply_rls_context
from app.models.notification import Notification, NotificationType


async def create_notification(
    session: AsyncSession,
    *,
    user_id: int,
    notification_type: NotificationType,
    data: Mapping[str, object],
) -> Notification:
    notification = Notification(user_id=user_id, type=notification_type, data=dict(data))
    session.add(notification)
    await session.flush()
    return notification


async def list_notifications(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int = 50,
) -> tuple[list[Notification], int]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    result = await session.exec(stmt)
    rows = result.all()
    notifications = [row[0] if isinstance(row, tuple) else row for row in rows]

    count_stmt = select(func.count()).where(
        Notification.user_id == user_id,
        Notification.read_at.is_(None),
    )
    count_result = await session.exec(count_stmt)
    unread_row = count_result.one()
    unread_count = unread_row[0] if isinstance(unread_row, tuple) else unread_row
    return notifications, unread_count


async def mark_notification_read(
    session: AsyncSession,
    *,
    user_id: int,
    notification_id: int,
) -> Notification | None:
    stmt = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == user_id,
    )
    result = await session.exec(stmt)
    row = result.one_or_none()
    if row is None:
        return None
    notification = row[0] if isinstance(row, tuple) else row
    if not notification:
        return None
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        session.add(notification)
        await session.commit()
        await reapply_rls_context(session)
        await session.refresh(notification)
    return notification


async def mark_all_notifications_read(
    session: AsyncSession,
    *,
    user_id: int,
) -> int:
    now = datetime.now(timezone.utc)
    stmt = (
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=now)
    )
    result = await session.exec(stmt)
    await session.commit()
    return result.rowcount or 0


async def unread_count(session: AsyncSession, *, user_id: int) -> int:
    stmt = select(func.count()).where(
        Notification.user_id == user_id,
        Notification.read_at.is_(None),
    )
    result = await session.exec(stmt)
    row = result.one()
    return row[0] if isinstance(row, tuple) else row
