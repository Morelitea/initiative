from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from sqlalchemy import func, tuple_, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import PERSONAL_TYPES, Channel
from app.models.platform.notification import Notification, NotificationType
from app.services.platform import notification_prefs, notification_stream


def _int_or_none(value: object) -> Optional[int]:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _place(data: Mapping[str, object]) -> dict[str, object]:
    """Where this happened, read off the payload that already carries it.

    Three independently-optional levels: a direct message has none of them, a
    membership notice has only a guild, a comment on a task has all three. Kept
    as columns so "where is there unread activity" is an index lookup.
    """
    # ``tool`` where the notifier states it outright, otherwise the entity type
    # it already carries. They differ for a task comment, whose entity is the
    # task and whose tool is the project list it lives in — and ``entity_type``
    # is what the link resolver reads, so it is not the place to say the other.
    tool = data.get("tool") or data.get("entity_type")
    return {
        "guild_id": _int_or_none(data.get("guild_id")),
        "initiative_id": _int_or_none(data.get("initiative_id")),
        "tool": tool if isinstance(tool, str) and tool else None,
    }


async def create_notification(
    session: AsyncSession,
    *,
    user_id: int,
    notification_type: NotificationType,
    data: Mapping[str, object],
    prefs: Optional[Mapping[str, Any]] = None,
) -> Optional[Notification]:
    """Write one notification, unless its recipient has switched the bell off
    for that category.

    Every notification in the app is written through here, which is what makes
    this the one place the in-app channel can be honoured. Returns ``None``
    when the recipient does not want it, so a caller can tell the difference
    between "wrote a line" and "there is nothing to point at".

    ``prefs`` is the recipient's settings document. Callers fanning out to an
    audience pass it from a batch load; a single-recipient caller leaves it
    None and this reads it.
    """
    place = _place(data)
    if prefs is None:
        prefs = await notification_prefs.load_prefs_for_delivery(user_id)
    if not notification_prefs.wants(
        prefs,
        notification_type=notification_type,
        channel=Channel.in_app,
        guild_id=place["guild_id"],
    ):
        return None

    notification = Notification(
        user_id=user_id,
        type=notification_type,
        data=dict(data),
        guild_id=place["guild_id"],
        initiative_id=place["initiative_id"],
        tool=place["tool"],
    )
    session.add(notification)
    await session.flush()
    # This one call is also what puts the recipient's open tabs on the realtime
    # channel instead of a 30s poll. The frame itself waits for this session's
    # COMMIT (see ``notification_stream``), so a caller that rolls back pokes
    # nobody.
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


def _decode_cursor(cursor: str | None) -> tuple[datetime, int] | None:
    """``<iso8601>|<id>`` — the sort key of the last row of the previous page.

    The id breaks ties, so two notifications written in the same instant cannot
    hide each other at a page boundary. A cursor that does not parse is treated
    as no cursor: a malformed one should start the list again, not fail it.
    """
    if not cursor:
        return None
    stamp, _, raw_id = cursor.partition("|")
    try:
        return datetime.fromisoformat(stamp), int(raw_id)
    except (ValueError, TypeError):
        return None


def encode_cursor(notification: Notification) -> str:
    return f"{notification.created_at.isoformat()}|{notification.id}"


async def list_notifications(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int = 50,
    cursor: str | None = None,
    unread_only: bool = False,
    guild_id: int | None = None,
    personal_only: bool = False,
) -> tuple[list[Notification], int, str | None]:
    """One page of the inbox, newest first, plus the unread total.

    Returns the cursor for the next page, or None at the end. The popover asks
    for ``unread_only`` and takes every page; the inbox page takes them as it
    is scrolled.
    """
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if guild_id is not None:
        stmt = stmt.where(Notification.guild_id == guild_id)
    if personal_only:
        stmt = stmt.where(Notification.type.in_(sorted(PERSONAL_TYPES)))
    position = _decode_cursor(cursor)
    if position is not None:
        stamp, last_id = position
        stmt = stmt.where(
            tuple_(Notification.created_at, Notification.id) < (stamp, last_id)
        )
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(
        limit + 1
    )
    result = await session.exec(stmt)
    rows = result.all()
    notifications = [row[0] if isinstance(row, tuple) else row for row in rows]
    # One more than asked for is how "is there another page" is answered
    # without a second count query.
    next_cursor = (
        encode_cursor(notifications[limit - 1]) if len(notifications) > limit else None
    )
    notifications = notifications[:limit]

    count_stmt = select(func.count()).where(
        Notification.user_id == user_id,
        Notification.read_at.is_(None),
    )
    count_result = await session.exec(count_stmt)
    unread_row = count_result.one()
    unread_count = unread_row[0] if isinstance(unread_row, tuple) else unread_row
    return notifications, unread_count, next_cursor


async def unread_places(
    session: AsyncSession, *, user_id: int
) -> list[tuple[int | None, int | None, str | None]]:
    """The distinct places this account has unread activity.

    One index-only scan over the partial index, returning a handful of triples
    — a node in the navigation lights when any of them names it as an ancestor.
    There is nothing to count: a dot says "look here", and the popover says how
    much. A row with no guild at all is still a member of this set, so "is
    anything unread" is the set being non-empty and needs no second question.
    """
    stmt = (
        select(Notification.guild_id, Notification.initiative_id, Notification.tool)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .distinct()
    )
    result = await session.exec(stmt)
    return [tuple(row) for row in result.all()]


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


async def mark_notification_unread(
    session: AsyncSession,
    *,
    user_id: int,
    notification_id: int,
) -> Notification | None:
    """Put a line back. Reading is a statement about the reader, and one made
    by accident should be retractable."""
    stmt = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == user_id,
    )
    result = await session.exec(stmt)
    row = result.one_or_none()
    if row is None:
        return None
    notification = row[0] if isinstance(row, tuple) else row
    if notification.read_at is not None:
        notification.read_at = None
        session.add(notification)
        notification_stream.queue_signal(session, user_id, "unread")
        await session.commit()
        await session.refresh(notification)
    return notification


async def dismiss_notification(
    session: AsyncSession,
    *,
    user_id: int,
    notification_id: int,
) -> bool:
    """Remove one line outright."""
    stmt = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == user_id,
    )
    result = await session.exec(stmt)
    row = result.one_or_none()
    if row is None:
        return False
    notification = row[0] if isinstance(row, tuple) else row
    await session.delete(notification)
    notification_stream.queue_signal(session, user_id, "withdrawn")
    await session.commit()
    return True


async def mark_all_notifications_read(
    session: AsyncSession,
    *,
    user_id: int,
    guild_id: int | None = None,
) -> int:
    """Clear the unread set, or just one community's part of it."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=now)
    )
    if guild_id is not None:
        stmt = stmt.where(Notification.guild_id == guild_id)
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
