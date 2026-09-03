"""Telling somebody they have a message, without saying what it is.

One rolled-up bell line per (recipient, conversation), exactly as reactions are
kept one line per (recipient, thing reacted to): a new message joins the
existing **unread** line and moves it back to the top, and once that line is
read the next message starts a fresh one, so "new" keeps meaning something.

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
from typing import Any, Mapping, cast

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.email_i18n import translate
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.services.platform import dm_stream, push_notifications, user_notifications

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
    if getattr(recipient, "push_direct_messages", True):
        await _push(session, recipient=recipient, sender_name=sender_name)
    if getattr(recipient, "email_direct_messages", True):
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
        only_device_token_ids=token_ids,
    )
