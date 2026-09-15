"""Telling somebody they have a message, without saying what it is.

One rolled-up bell line per (recipient, conversation), exactly as reactions are
kept one line per (recipient, thing reacted to): a new message joins the
existing **unread** line and moves it back to the top, and once that line is
read the next message starts a fresh one, so "new" keeps meaning something.

Reading the *thread* is what reads the line -- :func:`mark_conversation_read`,
called by the recipient's own client once it has rendered what arrived. The
server has no other way to know: it holds no message and cannot tell that one
reached a screen.

The line names the sender and counts the messages. It never carries one, and
nothing here adds a way for it to: the payload it announces is opaque on this
side.

This runs on the system engine rather than the sender's session. Writing a
notification and reading push tokens are both things the recipient's account
owns, and the sender has no business reaching either.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, cast

from sqlalchemy import delete, func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.email_i18n import translate
from app.core.notification_categories import Channel
from app.models.platform.notification import Notification, NotificationType
from app.models.platform.user import User
from app.services.platform import (
    dm_stream,
    notification_prefs,
    notification_stream,
    push_notifications,
    user_notifications,
)

logger = logging.getLogger(__name__)


def _locale(user: User) -> str:
    return getattr(user, "locale", None) or "en"


async def _lock_line(session: AsyncSession, key: str) -> None:
    """Serialize the read-then-write on one recipient's rolled-up line.

    Two messages landing at the same moment would otherwise both find no line to
    join and write one each. Transaction-scoped, and keyed narrowly enough that
    only messages in the same conversation ever wait.
    """
    await session.exec(
        select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0)))
    )


async def _dm_device_token_ids(session: AsyncSession, user_id: int) -> set[int]:
    """The installations of this account that could actually decrypt.

    A push wakes a client so it can fetch and decrypt. Sending one to an
    installation with no key store would wake it for something it cannot read.
    """
    from app.models.platform.dm_device import DmDevice

    rows = (
        await session.exec(
            select(DmDevice.device_token_id).where(
                DmDevice.user_id == user_id,
                DmDevice.device_token_id.is_not(None),
            )
        )
    ).all()
    return {row for row in rows if row is not None}


async def notify(
    *,
    recipient_id: int,
    sender: User,
    sender_name: str,
    conversation_id: uuid.UUID,
) -> None:
    """Roll one message into the recipient's bell line, then wake their tabs.

    Failures here are logged and swallowed: the message is already delivered,
    and a bell line is not worth failing a send over.
    """
    from app.db.session import AdminSessionLocal

    try:
        async with AdminSessionLocal() as session:
            recipient = await session.get(User, recipient_id)
            if recipient is None:
                return
            await _roll_up(
                session,
                recipient=recipient,
                sender=sender,
                sender_name=sender_name,
                conversation_id=conversation_id,
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - a bell line never fails a send
        logger.exception("direct-message notification failed")
    await dm_stream.signal_dm(recipient_id)


def _line_of(conversation_id: uuid.UUID):
    """Every rolled-up line this account holds for one conversation."""
    return (
        Notification.type == NotificationType.direct_message,
        Notification.data["conversation_id"].as_string() == str(conversation_id),
    )


async def mark_conversation_read(
    session: AsyncSession, *, user_id: int, conversation_id: uuid.UUID
) -> int:
    """Close this account's rolled-up line for one conversation.

    A line collects while it is unread, and the push and the email fire on the
    transition into unread rather than once per message. Closing the line is
    therefore what lets the next message announce itself at all, and reading the
    thread is what closes it -- there is nothing else that could, since the
    server cannot see a message arrive at a screen.

    Runs on the reader's own session: the line is theirs, and so is the claim
    that they have read it.
    """
    result = await session.exec(
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
            *_line_of(conversation_id),
        )
        .values(read_at=datetime.now(timezone.utc))
    )
    closed = result.rowcount or 0
    if closed:
        # The tab that read the thread already knows; this is for the account's
        # other tabs and devices, whose badge would keep the stale count.
        notification_stream.queue_signal(session, user_id, "read")
    return closed


async def forget_conversation(
    session: AsyncSession, *, user_id: int, conversation_id: uuid.UUID
) -> int:
    """Take down the lines for a conversation this account has left.

    Read or unread alike: the line names a thread that is no longer in the list,
    and tapping it would arrive at nothing.
    """
    result = await session.exec(
        delete(Notification).where(
            Notification.user_id == user_id,
            *_line_of(conversation_id),
        )
    )
    removed = result.rowcount or 0
    if removed:
        notification_stream.queue_signal(session, user_id, "withdrawn")
    return removed


async def wake_own_devices(*, user_id: int, except_device_token_id: int | None) -> None:
    """Push this account's other installations awake, saying nothing.

    One device has sent another something it cannot answer on its own -- a new
    install asking to be sent the history it arrived without. The far phone has
    to be picked up before anybody can approve it, so a frame on a socket that
    is not open will not do.

    No bell line: the ask is already on screen on the device that made it, and a
    second copy in the recipient's inbox would outlive the request. The one that
    sent it is skipped -- it is the device already showing the notice.

    The account's push preference applies: this rides the messages channel, and
    somebody who has said they do not want messages waking them has said it
    about this too.

    Quiet hours do not, and this is the one place in the app where they are
    skipped. Everywhere else a suppressed notification is only deferred -- the
    bell line is still written, and the "while you were away" summary collects
    it. This wake writes no bell line and is sent exactly once, because a device
    asks for its history once and never again, so suppressing it does not move
    the interruption to the morning; it deletes it, and leaves the new device
    waiting on an approval nobody was ever told to give. The person is also, by
    construction, awake and holding a device they signed into moments ago.
    """
    from app.db.session import AdminSessionLocal

    try:
        async with AdminSessionLocal() as session:
            user = await session.get(User, user_id)
            if user is None:
                return
            prefs = await notification_prefs.load_prefs_for_delivery(user_id)
            if not notification_prefs.wants(
                prefs,
                notification_type=NotificationType.direct_message,
                channel=Channel.push,
            ):
                return
            token_ids = await _dm_device_token_ids(session, user_id)
            token_ids.discard(except_device_token_id)
            if not token_ids:
                return
            locale = _locale(user)
            await push_notifications.send_push_to_user(
                session,
                user_id,
                NotificationType.direct_message,
                translate("deviceSync.title", locale, namespace="notifications"),
                translate("deviceSync.body", locale, namespace="notifications"),
                data={"type": "dm_device_sync", "target_path": "/messages"},
                only_device_token_ids=token_ids,
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - a wake never fails a send
        logger.exception("direct-message device wake failed")


async def _roll_up(
    session: AsyncSession,
    *,
    recipient: User,
    sender: User,
    sender_name: str,
    conversation_id: uuid.UUID,
) -> None:
    match = {"conversation_id": str(conversation_id)}
    await _lock_line(session, f"dm-bell:{conversation_id}:{recipient.id}")
    existing = await user_notifications.find_unread_by_data(
        session,
        user_id=recipient.id,
        notification_type=NotificationType.direct_message,
        match=match,
    )
    previous: Mapping[str, Any] = (existing.data if existing else None) or {}
    count = cast(int, previous.get("count", 0)) + 1
    line = {
        "conversation_id": str(conversation_id),
        "sender_id": sender.id,
        "sender_name": sender_name,
        "count": count,
    }
    if existing is None:
        await user_notifications.create_notification(
            session,
            user_id=recipient.id,
            notification_type=NotificationType.direct_message,
            data=line,
        )
    else:
        await user_notifications.refresh_notification(session, existing, data=line)

    # Both channels fire on the transition into unread, not per message: a
    # flurry is one notification rather than twenty, with nothing added to the
    # first. Once the line is read, the next message starts a fresh one and they
    # fire again.
    if existing is not None:
        return
    prefs = await notification_prefs.load_prefs_for_delivery(recipient.id)
    quiet = notification_prefs.in_quiet_hours(prefs, tz_name=recipient.timezone)

    def _wanted(channel: Channel) -> bool:
        if quiet and channel in notification_prefs.QUIET_CHANNELS:
            return False
        return notification_prefs.wants(
            prefs,
            notification_type=NotificationType.direct_message,
            channel=channel,
        )

    if _wanted(Channel.push):
        await _push(session, recipient=recipient, sender_name=sender_name)
    if _wanted(Channel.email):
        await _email(session, recipient=recipient, sender_name=sender_name)


async def _email(session: AsyncSession, *, recipient: User, sender_name: str) -> None:
    """Say a message is waiting. The name, and nothing else.

    A deployment with no SMTP configured is not an error here -- the bell line
    and the push have already been written, and email is the optional channel.
    """
    from app.core.config import settings as app_config
    from app.services import email as email_service

    link = f"{app_config.APP_URL.rstrip('/') or 'http://localhost:5173'}/messages"
    try:
        await email_service.send_direct_message_email(
            session, recipient, sender_name=sender_name, link=link
        )
    except email_service.EmailNotConfiguredError:
        return


async def _push(session: AsyncSession, *, recipient: User, sender_name: str) -> None:
    token_ids = await _dm_device_token_ids(session, recipient.id)
    if not token_ids:
        return
    locale = _locale(recipient)
    await push_notifications.send_push_to_user(
        session,
        recipient.id,
        NotificationType.direct_message,
        translate(
            "directMessage.title",
            locale,
            namespace="notifications",
            sender=sender_name,
        ),
        translate("directMessage.body", locale, namespace="notifications"),
        # Where tapping it goes, and nothing more. The conversation's id would
        # open the right thread, but it would also put a record of who is
        # talking to whom through a push service, which is the one thing this
        # feature is built not to do.
        data={
            "type": NotificationType.direct_message.value,
            "target_path": "/messages",
        },
        only_device_token_ids=token_ids,
    )
