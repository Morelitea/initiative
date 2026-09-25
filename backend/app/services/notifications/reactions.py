"""Reactions: one rolled-up bell line per thing reacted to, and a digest."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, cast

from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import SystemSessionLocal
from app.core.notification_categories import (
    NotificationCategory,
)
from app.models.tenant.reaction_digest import ReactionDigestItem
from app.models.platform.user import User
from app.models.platform.notification import NotificationType
from app.services import email as email_service
from app.services.platform import notification_policy
from app.services.platform import notification_prefs
from app.services.platform import user_notifications
from app.services.platform import push_notifications
from app.core.user_display import handle_of
from app.services.notifications.delivery import (
    MY_TASKS_TARGET_PATH,
    _build_smart_link,
    _nt,
    _recipient_locale,
)
from app.services.notifications.digests import (
    DigestSpec,
    _run_digest_pass,
    wants_digest,
)
from app.services.notifications.rollup import _lock_rollup_line

logger = logging.getLogger(__name__)


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
    target_path: str,
    smart_link: str | None,
    target_type: str,
    target_id: int,
    guild_id: int,
    initiative_id: int | None = None,
    tool: str | None = None,
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
        "guild_id": guild_id,
        "initiative_id": initiative_id,
        "tool": tool,
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


async def enqueue_reaction_event(
    session: AsyncSession,
    *,
    author: User,
    reactor: User,
    reaction,
    context_title: str,
    target_path: str,
    guild_id: int,
    initiative_id: int | None = None,
    tool: str | None = None,
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
    prefs = await notification_prefs.prefs_for_delivery(author)
    previous: Mapping[str, Any] = (existing.data if existing else None) or {}
    roster = _rolled_up_reactor_ids(previous)
    if reactor.id not in roster:
        roster.append(cast(int, reactor.id))
    line = _reaction_line(
        _rolled_up_reactions(previous) + [entry],
        count=_rolled_up_count(previous) + 1,
        reactor_ids=roster,
        target_path=target_path,
        smart_link=smart_link,
        target_type=reaction.target_type,
        target_id=reaction.target_id,
        guild_id=guild_id,
        initiative_id=initiative_id,
        tool=tool,
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
            target_path=previous.get("target_path") or MY_TASKS_TARGET_PATH,
            smart_link=previous.get("smart_link"),
            target_type=target_type,
            target_id=target_id,
            guild_id=guild_id,
            initiative_id=previous.get("initiative_id"),
            tool=previous.get("tool"),
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


async def _run_reaction_digest_pass(session: AsyncSession, *, now: datetime) -> None:
    """Send reaction digests. Split out from ``process_reaction_digests`` so
    tests can drive it with the test session."""
    await _run_digest_pass(session, REACTION_DIGEST, now=now)


async def process_reaction_digests() -> None:
    async with SystemSessionLocal() as session:
        await _run_reaction_digest_pass(session, now=datetime.now(timezone.utc))
