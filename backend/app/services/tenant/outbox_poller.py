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

Progress is a ledger row per ``(subscription, transaction)``, not a cursor, and
that is a correctness decision rather than a tuning one. Outbox ids come from a
sequence at insert time but are published at commit time, so a transaction still
in flight can put a row *beneath* any watermark chosen while that row was
invisible — and no query can see an uncommitted row to defend against it. A
ledger has nothing for a late row to be beneath: a transaction is either recorded
for a subscription or it is not.

What follows from that:

* **Nothing is skipped.** Work not taken this pass is still pending on the next.
  ``BATCH_LIMIT`` bounds throughput, never visibility.
* **Two replicas racing is settled by the database.** Claiming is an insert on
  the ledger's primary key; the loser gets no row and moves on.
* **A duplicate is recognizable as one.** ``event_id`` derives from
  ``(subscription_id, txn_id)``, so a batch redelivered after a lapsed claim
  carries the id a receiver already saw.

Only committed transactions are eligible — ``pg_visible_in_snapshot`` asks
exactly that, per transaction. Not the snapshot's xmin floor: xmin is the oldest
transaction still running ANYWHERE in the database, so comparing against it
holds every delivery hostage to one long-lived transaction that has nothing to
do with the outbox. This is about batch completeness, not cursor safety: half a
transaction is not a batch, and one skipped this pass is simply still pending
next pass.
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

#: How often delivered history is swept.
OUTBOX_RETENTION_POLL_SECONDS = 3600

#: Transactions a subscription may take in one pass. A throughput bound only —
#: anything not taken remains exactly as visible next pass.
BATCH_LIMIT = 50

#: How long a claim on one transaction is held before another pass may retry it.
LEASE_SECONDS = 300

#: Backoff schedule, in seconds, indexed by consecutive failures on a batch.
_BACKOFF_SECONDS = (5, 30, 120, 600, 1800, 3600)

#: The same schedule as a SQL array. The interval has to be chosen in the same
#: statement that increments ``attempts`` — computing it in Python would mean
#: reading the count, deciding, then writing, and two passes racing there would
#: each pick a step from a stale count. Postgres arrays are 1-indexed and
#: ``attempts`` in a SET expression is the pre-update value, so ``attempts + 1``
#: selects the step for the failure being recorded.
_BACKOFF_SQL_ARRAY = "(ARRAY[" + ",".join(str(s) for s in _BACKOFF_SECONDS) + "])"

#: Namespace for deterministic envelope ids. Fixed forever: changing it would
#: make every in-flight batch look new to a receiver deduping on event_id.
_EVENT_ID_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def _event_id(subscription_id: int, txn_id: int) -> str:
    """Same batch, same id — on any replica, on any retry."""
    return str(uuid.uuid5(_EVENT_ID_NAMESPACE, f"{subscription_id}:{txn_id}"))


def _event_type(row: EventOutbox) -> str:
    return f"{row.resource_type}.{row.action}"


def _matches(row: EventOutbox, subscription: WebhookSubscription) -> bool:
    """Whether one change-item belongs in this subscription's batch.

    Applied per item BEFORE the batch is assembled, so a column filter costs a
    set intersection and no request, and grouping by transaction never widens
    what a subscription receives.
    """
    if _event_type(row) not in subscription.event_types:
        return False
    if (
        subscription.initiative_id is not None
        and row.initiative_id != subscription.initiative_id
    ):
        return False
    if subscription.fields and row.action == "updated":
        # created/deleted report no columns — the whole row came or went — so a
        # column filter has nothing to say about them and does not apply.
        if not set(row.changed) & set(subscription.fields):
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


async def _pending_transactions(
    session: AsyncSession, subscription: WebhookSubscription, *, now: datetime
) -> list[int]:
    """Settled transactions this subscription still owes, oldest first.

    Ordered by the first outbox id each transaction wrote, so batches arrive
    roughly in the order they were created. Settled means the writing
    transaction is committed in our snapshot — checked per transaction, never
    against the snapshot's xmin floor, which an unrelated long-running
    transaction pins. Eligibility is "no ledger row yet" or "a row that failed
    and is out of backoff" — there is no position to maintain, so a transaction
    missed by one pass is simply still pending.

    The outbox read runs under the SUBSCRIPTION OWNER's context, so RLS has
    already removed transactions holding nothing that owner may see.
    """
    rows = await session.exec(
        text(
            "SELECT o.txn_id "
            "FROM event_outbox o "
            "WHERE pg_visible_in_snapshot(o.txn_id::text::xid8, pg_current_snapshot()) "
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM webhook_deliveries d "
            "    WHERE d.subscription_id = :sid AND d.txn_id = o.txn_id "
            "      AND (d.delivered_at IS NOT NULL OR d.next_attempt_at > :now)"
            "  ) "
            "GROUP BY o.txn_id "
            "ORDER BY min(o.id) ASC "
            "LIMIT :limit"
        ).bindparams(sid=subscription.id, now=now, limit=BATCH_LIMIT)
    )
    return [row[0] for row in rows]


async def _claim(
    session: AsyncSession,
    subscription: WebhookSubscription,
    txn_id: int,
    *,
    now: datetime,
) -> bool:
    """Take one transaction for this pass, or report that someone else has it.

    The ledger's primary key is the claim: an insert conflicting with a live row
    updates nothing and returns nothing, so the racing replica moves on. A row
    that exists but is out of backoff is re-taken by extending its lease.
    """
    result = await session.exec(
        text(
            "INSERT INTO webhook_deliveries "
            "  (subscription_id, txn_id, attempts, next_attempt_at) "
            "VALUES (:sid, :txn, 0, :lease) "
            "ON CONFLICT (subscription_id, txn_id) DO UPDATE "
            "  SET next_attempt_at = :lease "
            "  WHERE webhook_deliveries.delivered_at IS NULL "
            "    AND (webhook_deliveries.next_attempt_at IS NULL "
            "         OR webhook_deliveries.next_attempt_at <= :now) "
            "RETURNING attempts"
        ).bindparams(
            sid=subscription.id,
            txn=txn_id,
            lease=now + timedelta(seconds=LEASE_SECONDS),
            now=now,
        )
    )
    claimed = result.first() is not None
    await session.commit()
    return claimed


async def _settle(
    session: AsyncSession,
    subscription: WebhookSubscription,
    txn_id: int,
    *,
    now: datetime,
    accepted: bool,
) -> None:
    """Record the outcome.

    ``delivered_at IS NULL`` in the predicate keeps a pass whose lease lapsed
    mid-flight from reopening a batch another pass has already completed.
    """
    if accepted:
        statement = text(
            "UPDATE webhook_deliveries "
            "SET delivered_at = :now, next_attempt_at = NULL "
            "WHERE subscription_id = :sid AND txn_id = :txn AND delivered_at IS NULL"
        ).bindparams(now=now, sid=subscription.id, txn=txn_id)
    else:
        statement = text(
            "UPDATE webhook_deliveries "
            "SET attempts = attempts + 1, "
            "    next_attempt_at = :now + make_interval(secs => "
            f"      {_BACKOFF_SQL_ARRAY}[LEAST(attempts + 1, {len(_BACKOFF_SECONDS)})]"
            "    ) "
            "WHERE subscription_id = :sid AND txn_id = :txn AND delivered_at IS NULL"
        ).bindparams(now=now, sid=subscription.id, txn=txn_id)
    await session.exec(statement)
    await session.commit()


async def _drain_subscription(
    session: AsyncSession,
    subscription: WebhookSubscription,
    *,
    now: datetime,
) -> None:
    """Deliver one subscription's pending transactions, as its owner.

    The session is routed to the subscription's guild with the OWNER's user id,
    so every outbox read is gated by that owner's access. ``satisfied_providers``
    is the system sentinel: a background pass has no login to satisfy a guild's
    auth policy with, and that leg is about how a person authenticated, not about
    what this owner may reach. Every other gate applies unchanged.
    """
    await set_rls_context(
        session,
        user_id=subscription.created_by_user_id,
        guild_id=subscription.guild_id,
        satisfied_providers="system",
    )

    for txn_id in await _pending_transactions(session, subscription, now=now):
        if not await _claim(session, subscription, txn_id, now=now):
            continue

        rows = list(
            await session.exec(
                select(EventOutbox)
                .where(EventOutbox.txn_id == txn_id)
                .order_by(EventOutbox.id.asc())
            )
        )
        batch = [row for row in rows if _matches(row, subscription)]
        if not batch:
            # Nothing in this transaction was for this subscriber. Record it so
            # it is not reconsidered every pass; no request was made, so nothing
            # is claimed about the target.
            await _settle(session, subscription, txn_id, now=now, accepted=True)
            continue

        accepted = await deliver(
            target_url=subscription.target_url,
            secret=subscription.hmac_secret,
            envelope=_envelope(subscription, txn_id, batch),
        )
        await _settle(session, subscription, txn_id, now=now, accepted=accepted)
        if not accepted:
            # Deliver in order: hold the rest of this subscription's backlog
            # until the refused batch gets through.
            return


async def _drain_guild(session: AsyncSession, guild_id: int, *, now: datetime) -> None:
    # Read the subscription roster with full guild authority: which targets are
    # registered is guild configuration, not initiative content. What each of
    # them may then SEE is decided per subscription in _drain_subscription,
    # under its own owner's context.
    await set_rls_context(session, guild_id=guild_id, guild_role="admin")
    # Ids, not instances: each pass ends by expunging the identity map (ids
    # repeat across guild schemas), and an instance held across that is detached.
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
            await _drain_subscription(session, subscription, now=now)
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
    """Drop outbox history, and the ledger rows referencing it, past the window.

    Age-based on purpose: a subscription weeks behind is broken, and holding the
    log open for it would grow the table without bound on every instance that
    never configures a target at all. Ledger rows go with the events they
    describe, so the pair stays the same size.
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
            if not stale:
                await session.commit()
                continue
            txn_ids = sorted({row.txn_id for row in stale})
            for row in stale:
                await session.delete(row)
            await session.exec(
                text(
                    "DELETE FROM webhook_deliveries WHERE txn_id = ANY(:txn_ids)"
                ).bindparams(txn_ids=txn_ids)
            )
            logger.info("outbox retention: guild=%s removed=%s", guild_id, len(stale))
            await session.commit()
