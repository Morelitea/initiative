"""Drain ``event_outbox`` to each subscription's target.

The authorization decision is a query, not a check. For every subscription the
poller routes a session **as that subscription's owner** and reads the outbox
through it — so ``event_outbox``'s own initiative-member RLS returns exactly the
events that owner may currently see, and nothing here re-implements the six
gates. A guild-wide subscription therefore means "everything in this guild I can
reach", which is what it should mean, and it stays true as membership changes:
leaving an initiative, losing a PAM grant, or being deactivated all stop the
matching deliveries on the next pass with no subscription edit and no cache to
invalidate.

``initiative_id`` on the subscription is a narrowing filter on top of that, never
a widening one.

One transaction, one envelope: rows written by the same transaction share a
``txn_id`` and are delivered together, so a single user action that touched
fifty rows is one POST. Filtering still applies per change-item before the batch
is assembled, so batching costs nothing in precision.

A cursor advances only after a 2xx. A target that is down is retried on later
passes, backing off as failures accumulate, so an unreachable subscriber slows
its own deliveries instead of spinning.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

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

#: Rows read per subscription per pass. Bounds the work one badly-behind
#: subscription can do in a single cycle; the rest comes on the next pass.
BATCH_LIMIT = 500

#: Backoff schedule, in seconds, indexed by consecutive failure count. A target
#: that stays down is retried ever less often rather than every cycle.
_BACKOFF_SECONDS = (5, 30, 120, 600, 1800, 3600)


def _backoff(failure_count: int) -> timedelta:
    index = min(failure_count, len(_BACKOFF_SECONDS) - 1)
    return timedelta(seconds=_BACKOFF_SECONDS[index])


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
    subscription: WebhookSubscription, rows: list[EventOutbox]
) -> dict[str, Any]:
    """One transaction's matching rows as a single envelope.

    Carries identifiers and changed column NAMES only. A consumer reads current
    state back through the REST API, where the gates apply to the read.
    """
    first = rows[0]
    return {
        "event_id": str(uuid.uuid4()),
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

    rows = list(
        await session.exec(
            select(EventOutbox)
            .where(EventOutbox.id > subscription.cursor_event_id)
            .order_by(EventOutbox.id.asc())
            .limit(BATCH_LIMIT)
        )
    )
    if not rows:
        return

    # Group by transaction, preserving log order.
    batches: list[tuple[int, list[EventOutbox]]] = []
    for row in rows:
        if _matches(row, subscription):
            if batches and batches[-1][0] == row.txn_id:
                batches[-1][1].append(row)
            else:
                batches.append((row.txn_id, [row]))

    highest = rows[-1].id
    if not batches:
        # Nothing matched, but these rows are accounted for: skip past them so
        # a subscription with a narrow filter doesn't re-read the same window.
        await _advance(session, subscription, highest, now=now, delivered=True)
        return

    for _txn_id, batch in batches:
        ok = await deliver(
            target_url=subscription.target_url,
            secret=subscription.hmac_secret,
            envelope=_envelope(subscription, batch),
        )
        if not ok:
            # Stop at the first failure: the cursor stays behind this batch, so
            # it and everything after it are retried in order on a later pass.
            await _advance(
                session, subscription, batch[0].id - 1, now=now, delivered=False
            )
            return

    await _advance(session, subscription, highest, now=now, delivered=True)


async def _advance(
    session: AsyncSession,
    subscription: WebhookSubscription,
    cursor: int,
    *,
    now: datetime,
    delivered: bool,
) -> None:
    if cursor > subscription.cursor_event_id:
        subscription.cursor_event_id = cursor
    if delivered:
        subscription.failure_count = 0
        subscription.next_attempt_at = None
    else:
        subscription.failure_count += 1
        subscription.next_attempt_at = now + _backoff(subscription.failure_count)
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
        if (
            subscription.next_attempt_at is not None
            and subscription.next_attempt_at > now
        ):
            continue
        try:
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


async def process_outbox_deliveries() -> None:
    """One drain pass across every active guild. Idempotent."""
    now = datetime.now(timezone.utc)
    async with AdminSessionLocal() as session:
        await set_rls_context(session)
        guild_ids = list(
            await session.exec(
                select(Guild.id)
                .where(Guild.status == GuildStatus.active.value)
                .order_by(Guild.id.asc())
            )
        )
        for guild_id in guild_ids:
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
        await set_rls_context(session)
        guild_ids = list(
            await session.exec(
                select(Guild.id)
                .where(Guild.status == GuildStatus.active.value)
                .order_by(Guild.id.asc())
            )
        )
        for guild_id in guild_ids:
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
