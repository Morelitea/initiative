"""Notification email: written down, then sent.

Every notification email in the app is enqueued here and delivered by the
worker below. Three things follow from that, and they are the whole reason it
exists:

* **SMTP leaves the request path.** Creating a comment used to hold its
  transaction open across one SMTP connection per recipient.
* **A failed send is retried** rather than logged and lost. A row is claimed,
  attempted, and either settled or backed off — the ledger pattern the webhook
  poller already uses, against a table instead of a delivery log.
* **Several rows for one person can arrive as one message.** That is what makes
  a cadence possible at all, and it is what a hold releases when it lifts.

When a row may go out is decided once, at enqueue, by
:func:`~app.services.platform.notification_prefs.email_due_at` — the account's
cadence, floored by whatever is holding them. Changing a setting rewrites the
due time of everything still pending, which is what lets somebody resume early.

The table is append-only from the request path and read by nothing else: there
is no endpoint over it, and what the recipient sees is the email.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import insert, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import (
    Channel,
    NotificationCategory,
    sample_type,
)
from app.models.platform.email_outbox import EmailOutboxItem
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.models.platform.user_notification_prefs import EmailCadence
from app.services import email as email_service
from app.services.platform import notification_policy, notification_prefs

logger = logging.getLogger(__name__)

#: How often the worker looks for due mail. Email is not a realtime channel, so
#: the instant cadence losing a few seconds is invisible — and it is what buys
#: the retry that the synchronous send never had.
EMAIL_OUTBOX_POLL_SECONDS = 15

#: How long a claim is held before another pass may take the rows back. The
#: same lease the webhook ledger uses, for the same reason: a worker that died
#: mid-send must not strand its batch forever.
LEASE_SECONDS = 300

#: Backoff between attempts, in seconds, indexed by how many have failed.
BACKOFF_SECONDS = (5, 30, 120, 600, 1800, 3600)

#: How long a settled row is kept. Bookkeeping once the mail has gone, but
#: worth having while somebody might still ask whether it did.
RETENTION = timedelta(days=7)

#: Recipients handled per pass. Not a cap on anybody's mail — only on how many
#: people one pass serves before the next one starts.
BATCH_RECIPIENTS = 50


async def enqueue(
    session: AsyncSession,
    recipient: User,
    *,
    category: NotificationCategory,
    pieces: email_service.EmailPieces,
    guild_id: int | None = None,
    notification_id: int | None = None,
    prefs: Mapping[str, Any] | None = None,
    policy: notification_policy.NotificationPolicy | None = None,
) -> bool:
    """Write one notification email down.

    Runs on whatever session the notifier is already holding — a guild-routed
    request, usually — and appends to ``public.email_outbox``. An append, and
    only that: the row is the worker's from here on.

    Every notification email in the app is written here, which is where the
    deployment's and the community's answers about what may reach a mailbox are
    applied: one of them declining writes nothing, and either of them asking for
    a redacted notification stores the kind of thing that happened instead of
    what it was about — so the row carries no more than the mail will.

    ``prefs`` is the recipient's settings document, which the caller has
    already loaded to decide the email was wanted at all. ``policy`` is the same
    idea for the two switches, for a caller resolving them once across a batch.
    """
    if policy is None:
        policy = await notification_policy.load(guild_id)
    if not policy.email:
        return False
    if policy.redact:
        locale = getattr(recipient, "locale", None) or "en"
        pieces = email_service.EmailPieces(
            subject=notification_policy.redacted_subject(category, locale),
            headline=notification_policy.redacted_subject(category, locale),
            body=notification_policy.redacted_body(category, locale),
            link=pieces.link,
        )
    if not await email_service.email_configured(session):
        # Nothing to drain it, so nothing is written. A caller holding a queue
        # keeps it rather than treating this as delivered.
        return False
    if prefs is None:
        prefs = await notification_prefs.load_prefs_for_delivery(recipient.id)

    due = notification_prefs.email_due_at(
        prefs,
        notification_type=sample_type(category),
        tz_name=recipient.timezone,
        last_active_at=getattr(recipient, "last_active_at", None),
    )
    # Written without reading the row back: the generated id is never used
    # here, and the row is the worker's from this point.
    await session.exec(
        insert(EmailOutboxItem)
        .values(
            user_id=recipient.id,
            notification_id=notification_id,
            category=category.value,
            guild_id=guild_id,
            locale=getattr(recipient, "locale", None) or "en",
            subject=pieces.subject,
            headline=pieces.headline,
            body=pieces.body,
            link=pieces.link,
            link_label=pieces.link_label,
            created_at=datetime.now(timezone.utc),
            deliver_after=due,
        )
        .inline()
    )
    return True


async def recompute_pending(
    session: AsyncSession,
    *,
    user_id: int,
    prefs: Mapping[str, Any],
    tz_name: str | None,
    last_active_at: datetime | None = None,
) -> int:
    """Re-time everything this account has waiting.

    Called when a setting that decides *when* moves — the cadence, the clock,
    the weekday, the lane, a pause, the timezone. Without it, ending a pause
    early would leave a fortnight of mail sitting behind a date that has not
    arrived, which is not what "resume" can mean.

    Rows are re-timed from now rather than from when they were written: a
    message held for a week is news when the hold lifts, not a week late.
    """
    rows = (
        await session.exec(
            select(EmailOutboxItem).where(
                EmailOutboxItem.user_id == user_id,
                EmailOutboxItem.sent_at.is_(None),
                EmailOutboxItem.failed_at.is_(None),
            )
        )
    ).all()
    now = datetime.now(timezone.utc)
    moved = 0
    for row in rows:
        record = row[0] if isinstance(row, tuple) else row
        try:
            category = NotificationCategory(record.category)
        except ValueError:  # a category this build no longer has
            continue
        due = notification_prefs.email_due_at(
            prefs,
            notification_type=sample_type(category),
            tz_name=tz_name,
            last_active_at=last_active_at,
            now=now,
        )
        if due != record.deliver_after:
            record.deliver_after = due
            session.add(record)
            moved += 1
    if moved:
        await session.flush()
    return moved


def _reason(
    rows: Sequence[EmailOutboxItem],
    *,
    prefs: Mapping[str, Any],
    tz_name: str | None,
    now: datetime,
) -> str:
    """Why this batch is going out now, as the digest's own copy needs it.

    A hold that released them says so; otherwise it is simply the cadence
    coming round.
    """
    lift = notification_prefs.last_lift(prefs, tz_name=tz_name, now=now)
    if lift is not None and any(row.created_at < lift.closed for row in rows):
        return "away"
    cadence = notification_prefs.email_schedule(prefs).cadence
    if cadence is EmailCadence.instant:
        # Several at once under an instant cadence is a flurry, not a schedule.
        return "recent"
    return cadence.value


async def _guild_names(
    session: AsyncSession, rows: Sequence[EmailOutboxItem]
) -> dict[int, str]:
    ids = sorted({row.guild_id for row in rows if row.guild_id is not None})
    if not ids:
        return {}
    found = (await session.exec(select(Guild).where(Guild.id.in_(ids)))).all()
    out: dict[int, str] = {}
    for row in found:
        guild = row[0] if isinstance(row, tuple) else row
        if guild.id is not None:
            out[guild.id] = guild.name
    return out


async def _claim(
    session: AsyncSession, *, user_id: int, now: datetime
) -> list[EmailOutboxItem]:
    """Take this account's due rows, so a second worker cannot take them too.

    The claim and the read are one statement: two passes racing here would
    otherwise both see the same rows before either marked them.
    """
    result = await session.exec(
        text(
            "UPDATE email_outbox SET claimed_at = :now "
            "WHERE user_id = :uid AND sent_at IS NULL AND failed_at IS NULL "
            "  AND deliver_after <= :now "
            "  AND (claimed_at IS NULL OR claimed_at < :stale) "
            "RETURNING id, notification_id, category, guild_id, locale, subject, "
            "          headline, body, link, link_label, created_at"
        ).bindparams(
            now=now,
            uid=user_id,
            stale=now - timedelta(seconds=LEASE_SECONDS),
        )
    )
    return [
        EmailOutboxItem(
            id=row.id,
            user_id=user_id,
            notification_id=row.notification_id,
            category=row.category,
            guild_id=row.guild_id,
            locale=row.locale,
            subject=row.subject,
            headline=row.headline,
            body=row.body,
            link=row.link,
            link_label=row.link_label,
            created_at=row.created_at,
        )
        for row in result.all()
    ]


async def _discard(session: AsyncSession, ids: Sequence[int]) -> None:
    if not ids:
        return
    await session.exec(
        text("DELETE FROM email_outbox WHERE id = ANY(:ids)").bindparams(ids=list(ids))
    )


async def _already_read(
    session: AsyncSession, rows: Sequence[EmailOutboxItem]
) -> set[int]:
    """The rows whose bell line the recipient has since read.

    A digest is what is still waiting. Somebody who has already dealt with a
    mention in the app does not need to be told about it again by email — and a
    row with no bell line at all (the category's bell is switched off) has
    nothing that could supersede it.
    """
    ids = [row.notification_id for row in rows if row.notification_id is not None]
    if not ids:
        return set()
    result = await session.exec(
        text(
            "SELECT id FROM notifications WHERE id = ANY(:ids) AND read_at IS NOT NULL"
        ).bindparams(ids=ids)
    )
    read = {row.id for row in result.all()}
    return {
        row.id for row in rows if row.id is not None and row.notification_id in read
    }


async def _settle(session: AsyncSession, ids: Sequence[int], *, now: datetime) -> None:
    if not ids:
        return
    await session.exec(
        text(
            "UPDATE email_outbox SET sent_at = :now, claimed_at = NULL "
            "WHERE id = ANY(:ids)"
        ).bindparams(now=now, ids=list(ids))
    )


async def _back_off(
    session: AsyncSession, ids: Sequence[int], *, now: datetime
) -> None:
    """Return a failed batch to the queue, later each time.

    The step is chosen in the same statement that increments the count, so two
    passes racing here cannot both read a stale count and pick the same one.
    """
    if not ids:
        return
    await session.exec(
        text(
            "UPDATE email_outbox SET "
            "  attempts = attempts + 1, "
            "  claimed_at = NULL, "
            "  deliver_after = :now + make_interval("
            "      secs => (CAST(:backoff AS integer[]))["
            "        LEAST(attempts + 1, :steps)]), "
            "  failed_at = CASE WHEN attempts + 1 >= :steps THEN :now ELSE NULL END "
            "WHERE id = ANY(:ids)"
        ).bindparams(
            now=now,
            ids=list(ids),
            backoff=list(BACKOFF_SECONDS),
            steps=len(BACKOFF_SECONDS),
        )
    )


async def _send_one(
    session: AsyncSession, *, user: User, rows: list[EmailOutboxItem], now: datetime
) -> None:
    """Compose and send one account's due mail, then settle it."""
    prefs = await notification_prefs.load_prefs(session, user.id)

    # Anything read in the app on the way here, and anything the account has
    # switched off since it was written, is dropped rather than sent.
    stale = await _already_read(session, rows)
    refused = {
        row.id for row in rows if row.id not in stale and not _still_wanted(prefs, row)
    }
    await _discard(session, sorted(stale | refused))
    rows = [row for row in rows if row.id not in stale and row.id not in refused]
    if not rows:
        return

    _settings, accent = await email_service.email_context(session)
    locale = getattr(user, "locale", None) or "en"
    ids = [row.id for row in rows]
    try:
        if len(rows) == 1:
            row = rows[0]
            pieces = email_service.EmailPieces(
                subject=row.subject,
                headline=row.headline,
                body=row.body,
                link=row.link,
                link_label=row.link_label,
            )
            html_body, text_body = email_service.render_single(
                pieces, user=user, accent=accent, locale=row.locale or locale
            )
            subject = row.subject
        else:
            subject, html_body, text_body = email_service.render_digest(
                [
                    email_service.DigestLine(
                        category=row.category,
                        guild_id=row.guild_id,
                        body=row.body,
                        link=row.link,
                    )
                    for row in rows
                ],
                user=user,
                accent=accent,
                locale=locale,
                reason=_reason(rows, prefs=prefs, tz_name=user.timezone, now=now),
                guild_names=await _guild_names(session, rows),
            )
        await email_service.deliver(
            session, user, subject=subject, html_body=html_body, text_body=text_body
        )
    except email_service.EmailNotConfiguredError:
        # Mail was configured when these were written and is not now. Holding
        # them is right: nothing has been lost, and the next pass will find
        # them when it is configured again.
        await _back_off(session, ids, now=now)
        return
    except Exception:
        logger.exception("email-outbox: send failed for user %s", user.id)
        await _back_off(session, ids, now=now)
        return
    await _settle(session, ids, now=now)
    logger.info("email-outbox: sent %d item(s) to user %s", len(ids), user.id)


def _still_wanted(prefs: Mapping[str, Any], row: EmailOutboxItem) -> bool:
    try:
        category = NotificationCategory(row.category)
    except ValueError:
        return False
    return notification_prefs.wants(
        prefs,
        notification_type=sample_type(category),
        channel=Channel.email,
        guild_id=row.guild_id,
    )


async def _run_pass(session: AsyncSession, *, now: datetime) -> None:
    """Send whatever is due, one recipient at a time.

    Recipients do not queue behind each other: unlike a webhook subscription
    there is no order to keep, so one account's failing mail server holds up
    only that account.
    """
    result = await session.exec(
        text(
            "SELECT DISTINCT user_id FROM email_outbox "
            "WHERE deliver_after <= :now AND sent_at IS NULL AND failed_at IS NULL "
            "  AND (claimed_at IS NULL OR claimed_at < :stale) "
            "ORDER BY user_id LIMIT :limit"
        ).bindparams(
            now=now,
            stale=now - timedelta(seconds=LEASE_SECONDS),
            limit=BATCH_RECIPIENTS,
        )
    )
    user_ids = [row.user_id for row in result.all()]
    for user_id in user_ids:
        rows = await _claim(session, user_id=user_id, now=now)
        if not rows:
            continue
        user = (
            await session.exec(select(User).where(User.id == user_id))
        ).one_or_none()
        if user is None:
            # Deleted between the scan and the claim; the cascade will take
            # the rows, and there is nobody to send to meanwhile.
            await session.commit()
            continue
        await _send_one(session, user=user, rows=rows, now=now)
        await session.commit()


async def process_email_outbox() -> None:
    from app.db.session import AdminSessionLocal, set_rls_context

    async with AdminSessionLocal() as session:
        await set_rls_context(session)
        await _run_pass(session, now=datetime.now(timezone.utc))


async def sweep_settled(
    session: AsyncSession, *, now: Optional[datetime] = None
) -> int:
    """Drop rows that have gone out, or run out of attempts, and are old enough
    that nobody is still asking about them."""
    cutoff = (now or datetime.now(timezone.utc)) - RETENTION
    result = await session.exec(
        text(
            "DELETE FROM email_outbox "
            "WHERE (sent_at IS NOT NULL OR failed_at IS NOT NULL) "
            "  AND created_at < :cutoff"
        ).bindparams(cutoff=cutoff)
    )
    return result.rowcount or 0
