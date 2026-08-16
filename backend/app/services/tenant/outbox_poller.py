"""Drain ``event_outbox`` to each subscription's target.

The authorization decision is a query, not a check. For every subscription the
poller routes a session **as that subscription's owner** and reads the outbox
through it — so ``event_outbox``'s own initiative-member RLS returns exactly the
events that owner may currently see, and nothing here re-implements the six
gates. A guild-wide subscription therefore means "everything in this guild I can
reach", and it stays true as membership changes: leaving an initiative, losing a
PAM grant, or being deactivated all stop the matching deliveries on the next
pass with no subscription edit and no cache to invalidate.

``initiative_id`` on the subscription is a narrowing filter on top of that, never
a widening one.

Three properties this has to actually hold, not merely intend:

**A transaction is never split.** Rows carry the ``txid_current()`` that wrote
them, and one transaction's rows go out as one envelope. Ids alone don't give
that: they come from a sequence at insert time, so concurrent transactions
interleave and one transaction's rows sit either side of another's. Which
transactions have finished is therefore asked of the database — first and last
id per transaction — never inferred from a list of rows that some limit or
barrier has already shortened. A transaction still in flight bars the cursor
rather than being stepped over, which is what keeps a slow writer's events from
being lost to a reader that raced past their ids.

**One replica drains a subscription at a time.** Every replica runs this loop, so
a subscription is claimed with a conditional update before it is drained, and the
claim is a lease that expires if the holder dies.

**A duplicate is recognizable as one.** ``event_id`` is derived from
``(subscription_id, txn_id)``, so if a batch is somehow delivered twice — a lease
that lapsed mid-flight, a retry after an ambiguous timeout — both copies carry
the same id and a receiver deduping on it drops the second. A random id per
envelope would make every duplicate look like new work.

A cursor advances only after a 2xx. Failures accumulate a backoff, so a target
that is down slows its own deliveries instead of spinning.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db.session import AdminSessionLocal, set_rls_context
from app.models.platform.guild import Guild, GuildStatus
from app.models.tenant.event_outbox import EventOutbox
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.services.tenant.webhook_dispatcher import deliver

logger = logging.getLogger(__name__)

#: How often the drain runs.
OUTBOX_POLL_SECONDS = 5

#: How often drained history is swept.
OUTBOX_RETENTION_POLL_SECONDS = 3600

#: Transactions a subscription may take in one pass. Bounds a single pass, not
#: what stays visible: whatever is not taken is simply still pending next time.
BATCH_LIMIT = 500

#: How long a claim on a subscription is held. Long enough to cover a full
#: window of deliveries at the per-request timeout, short enough that a replica
#: dying mid-drain doesn't strand the subscription for long.
LEASE_SECONDS = 300

#: Backoff schedule, in seconds, indexed by consecutive failure count. A target
#: that stays down is retried ever less often rather than every cycle.
_BACKOFF_SECONDS = (5, 30, 120, 600, 1800, 3600)

#: Namespace for deterministic envelope ids. Fixed forever: changing it would
#: make every in-flight batch look new to a receiver deduping on event_id.
_EVENT_ID_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def _backoff(failure_count: int) -> timedelta:
    index = min(failure_count, len(_BACKOFF_SECONDS) - 1)
    return timedelta(seconds=_BACKOFF_SECONDS[index])


def _event_id(subscription_id: int, txn_id: int) -> str:
    """Same batch, same id — on any replica, on any retry."""
    return str(uuid.uuid5(_EVENT_ID_NAMESPACE, f"{subscription_id}:{txn_id}"))


def _event_type(row: EventOutbox) -> str:
    return f"{row.resource_type}.{row.action}"


def _matches(row: EventOutbox, subscription: WebhookSubscription) -> bool:
    """Whether one change-item belongs in this subscription's batch.

    Applied per item BEFORE the batch is assembled, so grouping by transaction
    never widens what a subscription receives.
    """
    if _event_type(row) not in subscription.event_types:
        return False
    if (
        subscription.initiative_id is not None
        and row.initiative_id != subscription.initiative_id
    ):
        return False
    return True


def _envelope(
    subscription: WebhookSubscription, txn_id: int, rows: list[EventOutbox]
) -> dict[str, Any]:
    """One transaction's matching rows as a single envelope.

    Carries identifiers and changed column NAMES only. A consumer reads current
    state back through the REST API, where the gates apply to the read.
    """
    first = rows[0]
    return {
        "event_id": _event_id(subscription.id, txn_id),
        "subscription_id": subscription.id,
        "guild_id": subscription.guild_id,
        "actor_user_id": first.actor_user_id,
        "occurred_at": first.occurred_at.isoformat(),
        "changes": [
            {
                "event_type": _event_type(row),
                "initiative_id": row.initiative_id,
                "resource": {"type": row.resource_type, "id": row.resource_id},
                "action": row.action,
                "changed": list(row.changed),
            }
            for row in rows
        ],
    }


async def _claim(
    session: AsyncSession, subscription: WebhookSubscription, *, now: datetime
) -> datetime | None:
    """Take this subscription for one pass, returning the lease that proves it.

    A conditional update is the claim: only the replica whose UPDATE matches a
    row proceeds. ``next_attempt_at`` doubles as the lease, so a holder that dies
    mid-drain releases it by expiry rather than stranding the subscription — and
    the value written is the token every later write is checked against, so a
    holder whose lease lapsed cannot settle over whoever took it next.
    """
    lease = now + timedelta(seconds=LEASE_SECONDS)
    result = await session.exec(
        text(
            "UPDATE webhook_subscriptions SET next_attempt_at = :lease "
            "WHERE id = :id AND (next_attempt_at IS NULL OR next_attempt_at <= :now) "
            "RETURNING id"
        ).bindparams(lease=lease, id=subscription.id, now=now)
    )
    claimed = result.first() is not None
    await session.commit()
    if not claimed:
        return None
    # The claim was raw SQL, so the in-memory instance still holds what it was
    # loaded with — including a cursor another replica may have advanced between
    # the load and the claim. Re-read before trusting any of its state.
    await session.refresh(subscription)
    return lease


async def _readable_window(
    session: AsyncSession, cursor: int
) -> tuple[list[EventOutbox], int | None]:
    """Rows safe to deliver now, and the id to advance to.

    Completeness is read from the database, never inferred from a windowed list
    of rows. Ids come from a sequence at insert time, so a transaction's rows
    interleave with other transactions' and can sit either side of any cut we
    make. A list that has been shortened — by a row limit, or by stopping at an
    in-flight row — makes the transactions inside it *look* finished, and
    treating that as truth splits one across two passes. Both halves then derive
    the same event_id from (subscription_id, txn_id), so a receiver deduping on
    it takes the first and discards the rest.

    So: ask Postgres for each undelivered transaction's first and last id, take
    only transactions that end below the first in-flight row, and stop at a
    point no remaining transaction spans.
    """
    xmin = await session.scalar(
        text("SELECT pg_snapshot_xmin(pg_current_snapshot())::text::bigint")
    )

    # A transaction still in flight is a hard barrier: it may yet insert rows
    # below any watermark we pick, and those would fall beneath the cursor.
    barrier = await session.scalar(
        select(func.min(EventOutbox.id))
        .where(EventOutbox.id > cursor)
        .where(EventOutbox.txn_id >= xmin)
    )

    spans = list(
        await session.exec(
            select(
                EventOutbox.txn_id,
                func.min(EventOutbox.id).label("first_id"),
                func.max(EventOutbox.id).label("last_id"),
            )
            .where(EventOutbox.id > cursor)
            .where(EventOutbox.txn_id < xmin)
            .group_by(EventOutbox.txn_id)
            .order_by(func.min(EventOutbox.id).asc())
        )
    )
    if barrier is not None:
        spans = [span for span in spans if span.last_id < barrier]
    if not spans:
        return [], None

    watermark = _safe_watermark(spans)
    if watermark is None:
        return [], None

    rows = list(
        await session.exec(
            select(EventOutbox)
            .where(EventOutbox.id > cursor, EventOutbox.id <= watermark)
            .order_by(EventOutbox.id.asc())
        )
    )
    return rows, watermark


def _safe_watermark(spans: list[Any]) -> int | None:
    """The highest id no remaining transaction straddles.

    ``spans`` are (txn_id, first_id, last_id) ordered by first_id. Walking them
    while tracking the furthest last_id seen gives the points where every
    transaction opened so far has also closed — the only ids a single-number
    cursor may stop on. Bounded by BATCH_LIMIT transactions so one pass cannot
    take an unbounded backlog; whatever is left is simply still pending.
    """
    watermark: int | None = None
    reach = 0
    for index, span in enumerate(spans):
        reach = max(reach, span.last_id)
        if index + 1 >= len(spans) or spans[index + 1].first_id > reach:
            watermark = reach
            if index + 1 >= BATCH_LIMIT:
                break
    return watermark


async def _drain_subscription(
    session: AsyncSession,
    subscription: WebhookSubscription,
    *,
    now: datetime,
    lease: datetime,
) -> None:
    """Deliver one subscription's pending events, as its owner.

    The session is routed to the subscription's guild with the OWNER's user id,
    so the outbox read is gated by that owner's access. ``satisfied_providers``
    is the system sentinel: a background pass has no login to satisfy a guild's
    auth policy with, and that leg is about how a person authenticated, not
    about what this owner may reach. Every other gate applies unchanged.
    """
    await set_rls_context(
        session,
        user_id=subscription.created_by_user_id,
        guild_id=subscription.guild_id,
        satisfied_providers="system",
    )

    rows, watermark = await _readable_window(session, subscription.cursor_event_id)
    if watermark is None:
        # Nothing settled to send. Release the lease without touching failure
        # state — no delivery was attempted, so nothing was proven either way.
        await _release(session, subscription, lease=lease)
        return

    # Group by transaction id, not by adjacency: concurrent commits interleave
    # ids, so one transaction's rows are not necessarily contiguous.
    grouped: dict[int, list[EventOutbox]] = {}
    for row in rows:
        if _matches(row, subscription):
            grouped.setdefault(row.txn_id, []).append(row)

    if not grouped:
        # The window held nothing for this subscription. Skip past it so a
        # narrow filter doesn't re-read the same rows forever — but this is not
        # a delivery, so failure state is left alone.
        await _advance(
            session, subscription, watermark, now=now, outcome=None, lease=lease
        )
        return

    # Oldest transaction first, so a receiver sees changes in the order they
    # were committed.
    for txn_id in sorted(grouped):
        batch = grouped[txn_id]
        ok = await deliver(
            target_url=subscription.target_url,
            secret=subscription.hmac_secret,
            envelope=_envelope(subscription, txn_id, batch),
        )
        if not ok:
            # Hold the cursor beneath this transaction so it and everything
            # after it retry in order.
            await _advance(
                session,
                subscription,
                batch[0].id - 1,
                now=now,
                outcome=False,
                lease=lease,
            )
            return

    await _advance(session, subscription, watermark, now=now, outcome=True, lease=lease)


def _next_retry_state(
    failure_count: int, *, outcome: bool | None, now: datetime
) -> tuple[int, datetime | None]:
    """The retry state an attempt leaves behind.

    ``outcome`` None means no request was made — a window that held nothing this
    subscriber wanted. That is not evidence about the target, so it must leave
    the failure count alone; treating it as success would let unrelated traffic
    clear a failing target's backoff.
    """
    if outcome is True:
        return 0, None
    if outcome is False:
        failed = failure_count + 1
        return failed, now + _backoff(failed)
    return failure_count, None


async def _release(
    session: AsyncSession, subscription: WebhookSubscription, *, lease: datetime
) -> None:
    """Drop the lease, leaving cursor and failure state untouched."""
    await _settle(session, subscription, lease=lease)


async def _advance(
    session: AsyncSession,
    subscription: WebhookSubscription,
    cursor: int,
    *,
    now: datetime,
    outcome: bool | None,
    lease: datetime,
) -> None:
    """Move the cursor and settle the lease.

    ``outcome`` is the result of an actual delivery attempt — True for accepted,
    False for refused, and None when no request was made. Only a real attempt
    moves failure state: a window that merely contained nothing this subscriber
    wanted must not clear a failing target's backoff.
    """
    failure_count, next_attempt = _next_retry_state(
        subscription.failure_count, outcome=outcome, now=now
    )
    await _settle(
        session,
        subscription,
        lease=lease,
        cursor=cursor,
        failure_count=failure_count,
        next_attempt=next_attempt,
    )


async def _settle(
    session: AsyncSession,
    subscription: WebhookSubscription,
    *,
    lease: datetime,
    cursor: int | None = None,
    failure_count: int | None = None,
    next_attempt: datetime | None = None,
) -> None:
    """Write final state, but only while this pass still holds the lease.

    A drain that overran its lease has already been taken over by another
    replica, and writing here would undo whatever that replica settled —
    regressing a cursor into events it already delivered, or clearing a backoff
    it just set. The ``next_attempt_at = :lease`` predicate is what makes this
    write a no-op in that case. GREATEST keeps the cursor monotonic even when
    two passes race legitimately.
    """
    result = await session.exec(
        text(
            "UPDATE webhook_subscriptions SET "
            "  cursor_event_id = GREATEST(cursor_event_id, :cursor), "
            "  failure_count = COALESCE(:failure_count, failure_count), "
            "  next_attempt_at = :next_attempt "
            "WHERE id = :id AND next_attempt_at = :lease "
            "RETURNING cursor_event_id"
        ).bindparams(
            cursor=cursor if cursor is not None else subscription.cursor_event_id,
            failure_count=failure_count,
            next_attempt=next_attempt,
            id=subscription.id,
            lease=lease,
        )
    )
    row = result.first()
    await session.commit()
    if row is None:
        logger.warning(
            "outbox settle skipped — lease no longer held: subscription=%s",
            subscription.id,
        )
        return
    # Keep the in-memory instance in step with what actually landed.
    subscription.cursor_event_id = row[0]
    if failure_count is not None:
        subscription.failure_count = failure_count
    subscription.next_attempt_at = next_attempt


async def _drain_guild(session: AsyncSession, guild_id: int, *, now: datetime) -> None:
    # Read the subscription roster with full guild authority: which targets are
    # registered is guild configuration, not initiative content. What each of
    # them may then SEE is decided per subscription in _drain_subscription,
    # under its own owner's context.
    await set_rls_context(session, guild_id=guild_id, guild_role="admin")
    # Ids, not instances. Each pass ends by expunging the identity map — ids
    # repeat across guild schemas, so instances must not survive the reroute —
    # and an instance held across that is detached, which makes the refresh
    # inside _claim raise. Holding the roster as instances therefore drained the
    # first subscription and failed every one after it.
    subscription_ids = list(
        await session.exec(
            select(WebhookSubscription.id)
            .where(WebhookSubscription.active.is_(True))
            .order_by(WebhookSubscription.id.asc())
        )
    )
    for subscription_id in subscription_ids:
        try:
            subscription = await session.get(WebhookSubscription, subscription_id)
            if subscription is None or not subscription.active:
                continue
            lease = await _claim(session, subscription, now=now)
            if lease is None:
                continue
            await _drain_subscription(session, subscription, now=now, lease=lease)
        except Exception:
            logger.exception(
                "outbox drain failed: guild=%s subscription=%s",
                guild_id,
                subscription_id,
            )
            await session.rollback()
        finally:
            session.expunge_all()
            await set_rls_context(session, guild_id=guild_id, guild_role="admin")


async def _active_guild_ids(session: AsyncSession) -> list[int]:
    await set_rls_context(session)
    return list(
        await session.exec(
            select(Guild.id)
            .where(Guild.status == GuildStatus.active.value)
            .order_by(Guild.id.asc())
        )
    )


async def process_outbox_deliveries() -> None:
    """One drain pass across every active guild. Idempotent."""
    now = datetime.now(timezone.utc)
    async with AdminSessionLocal() as session:
        for guild_id in await _active_guild_ids(session):
            session.expunge_all()
            await _drain_guild(session, guild_id, now=now)


async def process_outbox_retention() -> None:
    """Drop outbox history past the retention window.

    Age-based rather than cursor-based on purpose: a subscription that is weeks
    behind is broken, and holding the log open for it would grow the table
    without bound on every instance that never configures a target at all.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.WEBHOOK_OUTBOX_RETENTION_DAYS
    )
    async with AdminSessionLocal() as session:
        for guild_id in await _active_guild_ids(session):
            session.expunge_all()
            await set_rls_context(session, guild_id=guild_id, guild_role="admin")
            stale = list(
                await session.exec(
                    select(EventOutbox).where(EventOutbox.occurred_at < cutoff)
                )
            )
            for row in stale:
                await session.delete(row)
            if stale:
                logger.info(
                    "outbox retention: guild=%s removed=%s", guild_id, len(stale)
                )
            await session.commit()
