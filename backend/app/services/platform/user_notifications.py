from datetime import datetime, timezone
from typing import Mapping

from sqlalchemy import func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.notification import Notification, NotificationType
from app.services.platform import notification_stream


async def create_notification(
    session: AsyncSession,
    *,
    user_id: int,
    notification_type: NotificationType,
    data: Mapping[str, object],
) -> Notification:
    notification = Notification(
        user_id=user_id, type=notification_type, data=dict(data)
    )
    session.add(notification)
    await session.flush()
    # Every notification in the app is written through here, so this one call
    # is what puts the recipient's open tabs on the realtime channel instead of
    # a 30s poll. The frame itself waits for this session's COMMIT (see
    # ``notification_stream``), so a caller that rolls back pokes nobody.
    notification_stream.queue_signal(session, user_id, "created")
    return notification


async def find_unread_by_data(
    session: AsyncSession,
    *,
    user_id: int,
    notification_type: NotificationType,
    match: Mapping[str, object],
) -> Notification | None:
    """The newest UNREAD notification of this type whose ``data`` matches every
    key in ``match``, if there is one.

    This is what lets a notification stream roll up rather than repeat: a
    second event about the same thing updates the line the first one wrote
    instead of adding another. Unread is the whole window — once the recipient
    has seen a line, the next event starts a fresh one, which is what keeps
    "new" meaning something.
    """
    stmt = select(Notification).where(
        Notification.user_id == user_id,
        Notification.type == notification_type,
        Notification.read_at.is_(None),
    )
    for key, value in match.items():
        # ``->>`` compares as text, so the value is stringified to match how
        # Postgres renders it — an int in the payload reads back as "12".
        stmt = stmt.where(Notification.data[key].as_string() == str(value))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(
        1
    )
    result = await session.exec(stmt)
    row = result.one_or_none()
    if row is None:
        return None
    return row[0] if isinstance(row, tuple) else row


async def refresh_notification(
    session: AsyncSession,
    notification: Notification,
    *,
    data: Mapping[str, object],
    bump: bool = True,
) -> Notification:
    """Rewrite a notification's payload in place.

    ``bump`` says the line has something new to say, so it returns to the top
    of the inbox AND to unread. Unread matters for more than tidiness: the
    recipient can mark the line read between the lookup that found it and this
    write, and a rolled-up event landing on an already-read line would never be
    seen. Clearing the stamp is a no-op on the line this was meant for — it was
    unread when it was found — and the right answer when it is not.

    A withdrawal passes ``bump=False``: taking something away is not news, and
    must not resurrect a line the recipient has already dealt with.
    """
    notification.data = dict(data)
    if bump:
        notification.created_at = datetime.now(timezone.utc)
        notification.read_at = None
    session.add(notification)
    await session.flush()
    # A rolled-up line is the only trace a second event leaves, so it has to
    # reach the bell the same way a new row does — there is no poll behind the
    # signal to notice the rewrite later.
    notification_stream.queue_signal(
        session, notification.user_id, "updated" if bump else "withdrawn"
    )
    return notification


async def delete_notification(
    session: AsyncSession, notification: Notification
) -> None:
    """Remove a notification outright — used when every event it rolled up has
    been taken back, so the line has nothing left to say."""
    user_id = notification.user_id
    await session.delete(notification)
    await session.flush()
    # Read the recipient off before the delete — the instance is expunged, and
    # a bell still showing a withdrawn line is the thing this prevents.
    notification_stream.queue_signal(session, user_id, "withdrawn")


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
        # The tab that clicked already knows; this is for the user's *other*
        # tabs and devices, whose badge would otherwise keep the stale count.
        notification_stream.queue_signal(session, user_id, "read")
        await session.commit()
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
    notification_stream.queue_signal(session, user_id, "read")
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
