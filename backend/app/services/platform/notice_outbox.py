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
from typing import Any, Iterable, Mapping, Sequence, cast

from sqlalchemy import delete, func, insert, text, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import category_of
from app.db.request_context import Unattributed
from app.models.platform.notice_outbox import NoticeOutboxItem
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.services import email as email_service
from app.services.platform import (
    notification_policy,
    notification_prefs,
    push_config,
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


#: What a row says when its writer says nothing: no rollup, no push, no email.
_BLANK: dict[str, Any] = {
    **dict.fromkeys(
        (
            "rollup_key",
            "actor_id",
            "actor_name",
            "push_title",
            "push_body",
            "push_data",
            "email_subject",
            "email_headline",
            "email_body",
            "email_link",
            "email_link_label",
        )
    ),
    "email_names_line": True,
}


def row(
    user_id: int,
    guild_id: int | None,
    notification_type: NotificationType,
    data: Mapping[str, Any],
    *,
    kind: str = "notice",
    **fields: Any,
) -> dict[str, Any]:
    """One row for :func:`enqueue`, every column named, so any batch of them
    is one statement."""
    now = datetime.now(timezone.utc)
    return {
        **_BLANK,
        "user_id": user_id,
        "guild_id": guild_id,
        "type": notification_type.value,
        "kind": kind,
        "data": dict(data),
        "created_at": now,
        "deliver_after": now,
        **fields,
    }


def _policy_of(
    policies: Mapping[int | None, notification_policy.NotificationPolicy],
    guild_id: int | None,
    data: Mapping[str, Any],
) -> notification_policy.NotificationPolicy:
    """The answer a row is sent under: its community's, joined with every
    community a push of its own gathers from.

    Such a push goes while any of them still sends push. Once one of them has
    stopped, or any redacts, it says only the kind of thing that happened.
    """
    policy = policies[guild_id]
    gathered = [policies[gid] for gid in data.get("communities", ())]
    if not gathered:
        return policy
    sending = [answer for answer in gathered if answer.push]
    return policy.stricter_than(
        notification_policy.NotificationPolicy(
            push=bool(sending),
            email=all(answer.email for answer in gathered),
            redact=len(sending) < len(gathered)
            or any(answer.redact for answer in gathered),
        )
    )


async def notice(
    session: AsyncSession,
    recipient: User,
    notification_type: NotificationType,
    data: Mapping[str, Any],
    *,
    guild_id: int | None,
    push: tuple[str, str] | None = None,
    push_data: Mapping[str, Any] | None = None,
    email: email_service.EmailPieces | None = None,
    communities: Iterable[int | None] = (),
    **fields: Any,
) -> dict[str, Any]:
    """One recipient's row, holding no more than the notice may say.

    The deployment's and the community's switches are applied here as well as
    at send: a channel either has switched off is left empty, and where either
    redacts, the push and the email say the kind of thing that happened rather
    than what it was about. Whether the recipient wants each channel is the
    worker's question.

    ``communities`` are the ones a push of its own gathers from — a digest's,
    a hold summary's. The row keeps them, and each one's switches are applied
    alongside, here and at send.
    """
    gathered = sorted({gid for gid in communities if gid is not None})
    if gathered:
        data = {**data, "communities": gathered}
    policy = _policy_of(
        await notification_policy.for_send_many(session, {guild_id, *gathered}),
        guild_id,
        data,
    )
    category = category_of(notification_type)
    locale = getattr(recipient, "locale", None) or "en"
    if push is not None:
        push = notification_policy.apply(policy, push, category=category, locale=locale)
    if push is not None and not (await push_config.ensure_push_config_fresh()).enabled:
        push = None
    if email is not None:
        email = notification_policy.apply(
            policy, email, category=category, locale=locale
        )
    return row(
        cast(int, recipient.id),
        guild_id,
        notification_type,
        data,
        push_title=push[0] if push else None,
        push_body=push[1] if push else None,
        push_data=dict(push_data or {}) if push else None,
        email_subject=email.subject if email else None,
        email_headline=email.headline if email else None,
        email_body=email.body if email else None,
        email_link=email.link if email else None,
        email_link_label=email.link_label if email else None,
        **fields,
    )


async def enqueue(session: AsyncSession, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write these notices down on the caller's session.

    The rows go as the statement's parameters rather than one VALUES list, so
    the driver sends a row at a time in one round trip and an audience of
    thousands never meets the limit on values one statement may bind.

    An append and nothing else: the rows are the worker's from here, and the
    request path holds no right to read them back. The wake is sent the same
    way, so it goes out only if the caller's transaction commits.
    """
    if not rows:
        return
    # Written without reading anything back: the request path may not read
    # this table, and an insert left to itself returns each new row's id.
    await session.exec(insert(NoticeOutboxItem.__table__).inline(), params=list(rows))  # type: ignore[arg-type]
    await session.exec(select(func.pg_notify(CHANNEL, "")))


async def cancel_pending_reaction(
    session: AsyncSession, *, user_id: int, guild_id: int, reaction_id: int
) -> bool:
    """Drop a reaction still waiting to be rolled into ``user_id``'s line —
    one whose first attempt failed and is backing off. Returns whether there
    was one, in which case the line never held it and there is nothing more
    to take back."""
    dropped = await session.exec(
        delete(NoticeOutboxItem)
        .where(
            NoticeOutboxItem.user_id == user_id,  # type: ignore[arg-type]
            # Reaction ids are a community's own, so the community is part of
            # which reaction this is.
            NoticeOutboxItem.guild_id == guild_id,  # type: ignore[arg-type]
            NoticeOutboxItem.kind == "reaction",  # type: ignore[arg-type]
            # Not one this pass holds: that one has been rolled in already.
            NoticeOutboxItem.claimed_at.is_(None),  # type: ignore[union-attr]
            NoticeOutboxItem.data["entry"]["id"].as_integer() == reaction_id,  # type: ignore[index]
        )
        .returning(NoticeOutboxItem.id)
    )
    return bool(dropped.all())


async def _claim(session: AsyncSession, *, now: datetime) -> list[NoticeOutboxItem]:
    """Take every due row of the next batch of recipients.

    By recipient, so one person's notices are delivered by one pass in the
    order they were written — which is what keeps a reaction taken back behind
    the reaction. A recipient another pass is still delivering to waits for
    it. The claim is its own statement: a pass racing this one waits on the
    rows and then finds them taken.
    """
    stale = now - timedelta(seconds=LEASE_SECONDS)
    due = (
        NoticeOutboxItem.deliver_after <= now,  # type: ignore[operator]
        (NoticeOutboxItem.claimed_at.is_(None))  # type: ignore[union-attr]
        | (NoticeOutboxItem.claimed_at < stale),  # type: ignore[operator]
    )
    held = select(NoticeOutboxItem.user_id).where(
        NoticeOutboxItem.claimed_at >= stale  # type: ignore[operator]
    )
    user_ids = (
        await session.exec(
            select(NoticeOutboxItem.user_id)
            .where(*due, NoticeOutboxItem.user_id.not_in(held))  # type: ignore[attr-defined]
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
                    .where(
                        NoticeOutboxItem.id.in_(push),  # type: ignore[union-attr]
                        NoticeOutboxItem.bell_written_at.is_(None),  # type: ignore[union-attr]
                    )
                    # The push's attempts start here: failures writing the
                    # bell line are not the push's to spend.
                    .values(bell_written_at=now, attempts=0)
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
        session,
        {row.guild_id for row in rows}
        | {gid for row in rows for gid in row.data.get("communities", ())},
    )
    allowed: list[NoticeOutboxItem] = []
    pushes: list[push_notifications.Push] = []
    for row in rows:
        notification_type = NotificationType(row.type)
        shown = notification_policy.apply(
            _policy_of(policies, row.guild_id, row.data),
            (row.push_title or "", row.push_body or ""),
            category=category_of(notification_type),
            locale=getattr(accounts.get(row.user_id), "locale", None) or "en",
        )
        if shown is None:
            continue
        allowed.append(row)
        pushes.append(
            push_notifications.Push(
                user_id=row.user_id,
                notification_type=notification_type,
                title=shown[0],
                body=shown[1],
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
