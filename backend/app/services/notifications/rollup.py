"""Rolling a flurry of comments on one thread into one unread line."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.platform.notification import Notification, NotificationType
from app.services.platform import user_notifications


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


def _comment_rollup_key(entity_type: str, entity_id: int) -> str:
    """What decides which line a comment joins: the thing being commented on.

    Not the comment — the point is that twenty comments on one task are one
    line rather than twenty.
    """
    return f"{entity_type}:{entity_id}"


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
    with no id.
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
