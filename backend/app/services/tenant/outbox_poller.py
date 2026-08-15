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
that: concurrent commits interleave them, and a fixed window can cut a
transaction in half. So the window stops at the first row belonging to a
transaction that is still in flight (``txn_id >= xmin``), and grouping is by
``txn_id``, not by adjacency. An open transaction holds the cursor rather than
being skipped — which is also what keeps a slow writer's events from being lost
to a later reader that raced past their ids.

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

from sqlalchemy import text
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

#: Rows examined per subscription per pass. The window may return slightly more
#: than this so a transaction is never cut in half.
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
) -> bool:
    """Take this subscription for one pass, or report that someone else has it.

    A conditional update is the claim: only the replica whose UPDATE matches a
    row proceeds. ``next_attempt_at`` doubles as the lease, so a holder that dies
    mid-drain releases it by expiry rather than stranding the subscription.
    """
    result = await session.exec(
        text(
            "UPDATE webhook_subscriptions SET next_attempt_at = :lease "
            "WHERE id = :id AND (next_attempt_at IS NULL OR next_attempt_at <= :now) "
            "RETURNING id"
        ).bindparams(
            lease=now + timedelta(seconds=LEASE_SECONDS),
            id=subscription.id,
            now=now,
        )
    )
    claimed = result.first() is not None
    await session.commit()
    if claimed:
        # The claim was raw SQL, so the in-memory instance still holds what it
        # was loaded with — including a cursor another replica may have advanced
        # between the load and the claim. Every later write goes through this
        # object, so re-read it before trusting any of its state.
        await session.refresh(subscription)
    return claimed


async def _readable_window(
    session: AsyncSession, cursor: int
) -> tuple[list[EventOutbox], int | None]:
    """Rows safe to deliver now, and the id to advance to.

    Stops at the first row whose transaction is still in flight. Everything
    before it belongs to a committed transaction, so no later insert can appear
    beneath the returned watermark and be skipped.
    """
    xmin = await session.scalar(
        text("SELECT pg_snapshot_xmin(pg_current_snapshot())::text::bigint")
    )
    rows = list(
        await session.exec(
            select(EventOutbox)
            .where(EventOutbox.id > cursor)
            .order_by(EventOutbox.id.asc())
            .limit(BATCH_LIMIT)
        )
    )
    settled: list[EventOutbox] = []
    for row in rows:
        if xmin is not None and row.txn_id >= xmin:
            # This transaction has not finished. Stop here: delivering past it
            # would let its rows fall below the cursor once it commits.
            break
        settled.append(row)
    if not settled:
        return [], None

    if len(rows) == BATCH_LIMIT and settled[-1] is rows[-1]:
        # The window ended exactly at the row limit, so the last transaction may
        # continue past it. Drop its rows and take them whole next pass —
        # otherwise one transaction arrives as two envelopes.
        tail_txn = settled[-1].txn_id
        trimmed = [row for row in settled if row.txn_id != tail_txn]
        if trimmed:
            return trimmed, trimmed[-1].id
        # The whole window is one transaction, so trimming would make no
        # progress ever. Read that transaction in full instead.
        whole = list(
            await session.exec(
                select(EventOutbox)
                .where(EventOutbox.id > cursor, EventOutbox.txn_id == tail_txn)
                .order_by(EventOutbox.id.asc())
            )
        )
        return whole, whole[-1].id

    return settled, settled[-1].id


async def _drain_subscription(
    session: AsyncSession,
    subscription: WebhookSubscription,
    *,
    now: datetime,
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
        await _release(session, subscription)
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
        await _advance(session, subscription, watermark, now=now, outcome=None)
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
                session, subscription, batch[0].id - 1, now=now, outcome=False
            )
            return

    await _advance(session, subscription, watermark, now=now, outcome=True)


async def _release(session: AsyncSession, subscription: WebhookSubscription) -> None:
    """Drop the lease, leaving failure state untouched."""
    subscription.next_attempt_at = None
    session.add(subscription)
    await session.commit()


async def _advance(
    session: AsyncSession,
    subscription: WebhookSubscription,
    cursor: int,
    *,
    now: datetime,
    outcome: bool | None,
) -> None:
    """Move the cursor and settle the lease.

    ``outcome`` is the result of an actual delivery attempt — True for accepted,
    False for refused, and None when no request was made. Only a real attempt
    moves failure state: a window that merely contained nothing this subscriber
    wanted must not clear a failing target's backoff.
    """
    if cursor > subscription.cursor_event_id:
        subscription.cursor_event_id = cursor
    if outcome is True:
        subscription.failure_count = 0
        subscription.next_attempt_at = None
    elif outcome is False:
        subscription.failure_count += 1
        subscription.next_attempt_at = now + _backoff(subscription.failure_count)
    else:
        subscription.next_attempt_at = None
    session.add(subscription)
    await session.commit()


async def _drain_guild(session: AsyncSession, guild_id: int, *, now: datetime) -> None:
    # Read the subscription roster with full guild authority: which targets are
    # registered is guild configuration, not initiative content. What each of
    # them may then SEE is decided per subscription in _drain_subscription,
    # under its own owner's context.
    await set_rls_context(session, guild_id=guild_id, guild_role="admin")
    subscriptions = list(
        await session.exec(
            select(WebhookSubscription)
            .where(WebhookSubscription.active.is_(True))
            .order_by(WebhookSubscription.id.asc())
        )
    )
    for subscription in subscriptions:
        try:
            if not await _claim(session, subscription, now=now):
                continue
            await _drain_subscription(session, subscription, now=now)
        except Exception:
            logger.exception(
                "outbox drain failed: guild=%s subscription=%s",
                guild_id,
                subscription.id,
            )
            await session.rollback()
        finally:
            # ids repeat across guild schemas, and the next subscription
            # re-routes the session.
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
