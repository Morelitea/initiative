"""Notices: written down in the request, delivered by a worker.

:func:`~app.services.notifications.notify` decides who hears about something
and what it says, and :func:`enqueue` writes one row per recipient in the
caller's transaction. The worker below delivers them: the bell line and the
email in one transaction per recipient, then every push of the pass at once.

Three things follow from the split:

* **Delivery leaves the request path.** A post that reaches a thousand people
  costs its request one insert, not a thousand bell writes and FCM calls.
* **The request that caused a notice is what it rides on.** The rows and the
  wake go out with its commit, so a request that rolls back tells nobody.
* **The bell line and the email are written once.** They are written, and the
  row marked, in one transaction. A push that fails short of an answer is
  tried again later; one that crashes mid-send is sent again after the lease,
  so a push may rarely arrive twice and is never silently lost.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import delete, func, insert, text, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.request_context import Unattributed
from app.models.platform.notice_outbox import NoticeOutboxItem
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.services.platform import (
    notification_policy,
    notification_prefs,
    push_notifications,
)

logger = logging.getLogger(__name__)

#: The channel a committed enqueue wakes the worker on.
CHANNEL = "notice_outbox"

#: How long the worker waits without a wake before looking anyway, for a wake
#: lost while its bus connection was being rebuilt.
NOTICE_OUTBOX_POLL_SECONDS = 15

#: How long a claim is held before another pass may take the rows back.
LEASE_SECONDS = 300

#: Backoff between attempts, in seconds, indexed by how many have failed. A
#: push past the last is given up; a bell line never is, and keeps trying at
#: the last step.
BACKOFF_SECONDS = (30, 120, 600, 1800)

#: Recipients one pass serves before the next one starts.
BATCH_RECIPIENTS = 100


async def enqueue(session: AsyncSession, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write these notices down, in one statement, on the caller's session.

    An append and nothing else: the rows are the worker's from here, and the
    request path holds no right to read them back. The wake is sent the same
    way, so it goes out only if the caller's transaction commits.
    """
    if not rows:
        return
    await session.exec(insert(NoticeOutboxItem).values(list(rows)).inline())
    await session.exec(select(func.pg_notify(CHANNEL, "")))


async def _claim(session: AsyncSession, *, now: datetime) -> list[NoticeOutboxItem]:
    """Take every due row of the next batch of recipients.

    By recipient, so one person's notices are delivered by one pass in the
    order they were written. The claim is its own statement: a pass racing
    this one waits on the rows and then finds them taken.
    """
    stale = now - timedelta(seconds=LEASE_SECONDS)
    due = (
        NoticeOutboxItem.deliver_after <= now,  # type: ignore[operator]
        (NoticeOutboxItem.claimed_at.is_(None))  # type: ignore[union-attr]
        | (NoticeOutboxItem.claimed_at < stale),  # type: ignore[operator]
    )
    user_ids = (
        await session.exec(
            select(NoticeOutboxItem.user_id)
            .where(*due)
            .distinct()
            .order_by(NoticeOutboxItem.user_id)
            .limit(BATCH_RECIPIENTS)
        )
    ).all()
    if not user_ids:
        return []
    claimed = await session.exec(
        update(NoticeOutboxItem)
        .where(NoticeOutboxItem.user_id.in_(user_ids), *due)  # type: ignore[attr-defined]
        .values(claimed_at=now)
        .returning(NoticeOutboxItem)
        .execution_options(synchronize_session=False)
    )
    return sorted(claimed.scalars().all(), key=lambda row: row.id or 0)


async def _drop(session: AsyncSession, ids: Sequence[int]) -> None:
    if ids:
        await session.exec(
            delete(NoticeOutboxItem).where(NoticeOutboxItem.id.in_(ids))  # type: ignore[union-attr]
        )


async def _back_off(
    session: AsyncSession, ids: Sequence[int], *, now: datetime, give_up: bool
) -> None:
    """Return rows to the queue, later each time. With ``give_up`` — a push
    whose bell line is already written — a row that has had every attempt is
    dropped instead; nothing is ever dropped before its bell line exists."""
    if not ids:
        return
    if give_up:
        spent = await session.exec(
            text(
                "DELETE FROM notice_outbox "
                "WHERE id = ANY(:ids) AND attempts + 1 >= :steps RETURNING user_id"
            ).bindparams(ids=list(ids), steps=len(BACKOFF_SECONDS))
        )
        for row in spent.all():
            logger.warning("notice-outbox: gave up a push for user %s", row.user_id)
    await session.exec(
        text(
            "UPDATE notice_outbox SET "
            "  attempts = attempts + 1, "
            "  claimed_at = NULL, "
            "  deliver_after = :now + make_interval("
            "      secs => (CAST(:backoff AS integer[]))["
            "        LEAST(attempts + 1, :steps)]) "
            "WHERE id = ANY(:ids)"
        ).bindparams(
            now=now,
            ids=list(ids),
            backoff=list(BACKOFF_SECONDS),
            steps=len(BACKOFF_SECONDS),
        )
    )


async def _run_pass(session: AsyncSession, *, now: datetime) -> bool:
    """Deliver one batch. Returns whether there may be more waiting."""
    from app.services import notifications

    rows = await _claim(session, now=now)
    await session.commit()
    if not rows:
        return False
    by_user: dict[int, list[NoticeOutboxItem]] = defaultdict(list)
    for row in rows:
        by_user[row.user_id].append(row)
    accounts = {
        user.id: user
        for user in (
            await session.exec(select(User).where(User.id.in_(list(by_user))))  # type: ignore[union-attr]
        ).all()
    }
    prefs = await notification_prefs.load_prefs_for(session, list(by_user))
    # Held apart from the session, so a recipient whose delivery is rolled
    # back does not take everybody else's loaded rows with them.
    session.expunge_all()

    pushing: list[NoticeOutboxItem] = []
    for user_id, notices in by_user.items():
        ids = [row.id for row in notices if row.id is not None]
        recipient = accounts.get(user_id)
        if recipient is None:
            # Erased since; the cascade takes the rows, and there is nobody
            # to tell meanwhile.
            await _drop(session, ids)
            await session.commit()
            continue
        try:
            push = await notifications.deliver_notices(
                session, recipient, notices, prefs.get(user_id, {})
            )
            await _drop(session, [i for i in ids if i not in push])
            if push:
                await session.exec(
                    update(NoticeOutboxItem)
                    .where(NoticeOutboxItem.id.in_(push))  # type: ignore[union-attr]
                    .values(bell_written_at=now)
                    .execution_options(synchronize_session=False)
                )
            await session.commit()
        except Exception:
            logger.exception("notice-outbox: delivery failed for user %s", user_id)
            await session.rollback()
            await _back_off(session, ids, now=now, give_up=False)
            await session.commit()
            continue
        pushing.extend(row for row in notices if row.id in push)

    if pushing:
        try:
            await _push(session, pushing, accounts, now=now)
        except Exception:
            logger.exception("notice-outbox: sending a batch of pushes failed")
            await session.rollback()
            await _back_off(
                session, [row.id for row in pushing if row.id], now=now, give_up=True
            )
        await session.commit()
    return len(by_user) == BATCH_RECIPIENTS


async def _push(
    session: AsyncSession,
    rows: Sequence[NoticeOutboxItem],
    accounts: Mapping[int, User],
    *,
    now: datetime,
) -> None:
    """Send these rows' pushes and settle them, under the switches as they
    stand now: a community that has turned push off since sends nothing, and
    one that has started redacting sends the kind of thing that happened."""
    policies = await notification_policy.for_send_many(
        session, {row.guild_id for row in rows}
    )
    allowed = [row for row in rows if policies[row.guild_id].push]
    pushes = []
    for row in allowed:
        notification_type = NotificationType(row.type)
        title, body = row.push_title or "", row.push_body or ""
        if policies[row.guild_id].redact:
            locale = getattr(accounts.get(row.user_id), "locale", None) or "en"
            title, body = notification_policy.redacted_push(notification_type, locale)
        pushes.append(
            push_notifications.Push(
                user_id=row.user_id,
                notification_type=notification_type,
                title=title,
                body=body,
                data=dict(row.push_data or {}),
            )
        )
    again = await push_notifications.send_pushes(session, pushes)
    retry = {row.id for row, answer in zip(allowed, again) if answer and row.id}
    await _drop(session, [row.id for row in rows if row.id and row.id not in retry])
    await _back_off(session, sorted(retry), now=now, give_up=True)


async def process_notice_outbox() -> None:
    """Deliver everything that is due, a batch at a time."""
    from app.db.session import SystemSessionLocal, set_rls_context

    async with SystemSessionLocal() as session:
        await set_rls_context(session, Unattributed())
        while await _run_pass(session, now=datetime.now(timezone.utc)):
            pass


#: Set by a wake; created by :func:`run`, so it belongs to the running loop.
_wake: asyncio.Event | None = None


async def hint(_payload: str) -> None:
    """A committed transaction wrote notices. Registered on :data:`CHANNEL`."""
    if _wake is not None:
        _wake.set()


async def run() -> None:
    """Deliver as notices arrive, and every :data:`NOTICE_OUTBOX_POLL_SECONDS`
    in case a wake went missing."""
    global _wake
    _wake = asyncio.Event()
    logger.info("notice-outbox worker started")
    while True:
        _wake.clear()
        try:
            await process_notice_outbox()
        except Exception:  # pragma: no cover
            logger.exception("notice-outbox worker encountered an error")
        try:
            await asyncio.wait_for(_wake.wait(), timeout=NOTICE_OUTBOX_POLL_SECONDS)
        except TimeoutError:
            pass
