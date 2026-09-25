"""Drain ``event_outbox`` to each subscription's target.

**A subscription's reach is the scope it names.** ``initiative_id`` set means
that initiative's changes; naming none means the community's. ``_matches``
applies it per change item, before a batch is assembled, and that is the whole
of the decision — no account's standing is consulted anywhere in a pass.

A subscription an installed app registered is also capped by the app's reach
as it is now: the install is live, it is placed in the change's initiative, and
its grant holds the read scope of what changed. That is read with the roster,
one statement per guild per pass (:class:`InstallReach`), so removing a
placement or a scope stops delivery from the next pass on.

That is the right granularity because of what a delivery is. An envelope is
identifiers and changed column **names**; a consumer reads current state back
through the REST path, where every gate applies to the read. An installed app
calling back presents its own token, whose standing is read on every call — so
what an app may *do*, and the instant at which it stops being able to, is
decided there rather than here.

A subscription is therefore the community's integration configuration, not the
personal property of whoever registered it: it outlives their membership, their
role and their account, and ending it is a decision somebody makes rather than a
side effect of an unrelated one. See ``history/webhook-scope-not-principal-design.md``.

Progress is a ledger row per ``(subscription, transaction)``, not a cursor, and
that is a correctness decision rather than a tuning one. Outbox ids come from a
sequence at insert time but are published at commit time, so a transaction still
in flight can put a row *beneath* any watermark chosen while that row was
invisible — and no query can see an uncommitted row to defend against it. A
ledger has nothing for a late row to be beneath: a transaction is either recorded
for a subscription or it is not.

What follows from that:

* **Nothing is skipped before it has to be.** Work not taken this pass is still
  pending on the next. ``BATCH_LIMIT`` bounds throughput, never visibility. A
  batch that exhausts ``_BACKOFF_SECONDS`` without a 2xx is the one exception —
  it is dead-lettered (``dead_lettered_at`` set, no further attempt scheduled)
  so a permanently unreachable target can't hold every later transaction
  hostage forever.
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

import asyncio

import logging
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import ARRAY, Integer, and_, bindparam, func, or_, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import webhook_events
from app.core.app_scopes import UnknownAppScope, expand
from app.db.session import (
    set_rls_context,
    set_system_guild_context,
)
from app.models.tenant.app_placement import AppPlacement
from app.models.tenant.event_outbox import EventOutbox
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.services.guild_sweeps import Drain
from app.services.marketplace.registration_lookup import load_registrations
from app.services.tenant import room_sink, webhook_refs
from app.services.tenant.webhook_dispatcher import deliver

logger = logging.getLogger(__name__)

#: How long the drain lets further changes gather before it visits.
DRAIN_SETTLE_SECONDS = 1.0

#: How long delivered change events are kept. A subscriber further behind than
#: this has stopped consuming and resumes from the current head.
OUTBOX_RETENTION_DAYS = 7

#: Transactions a subscription may take in one pass. A throughput bound only —
#: anything not taken remains exactly as visible next pass.
BATCH_LIMIT = 50

#: How long a claim on one transaction is held before another pass may retry it.
LEASE_SECONDS = 300

#: Backoff schedule, in seconds, indexed by consecutive failures on a batch.
_BACKOFF_SECONDS = (5, 30, 120, 600, 1800, 3600)
#: A retry due sooner than this is woken for; a later one waits for the minute
#: pass, which comes round at least this often.
RETRY_WAKE_WITHIN_SECONDS = 60

#: The same schedule, bound as an array parameter. The interval has to be chosen
#: in the same statement that increments ``attempts`` — computing it in Python
#: would mean reading the count, deciding, then writing, and two passes racing
#: there would each pick a step from a stale count. Postgres arrays are 1-indexed
#: and ``attempts`` in a SET expression is the pre-update value, so
#: ``attempts + 1`` selects the step for the failure being recorded.
_BACKOFF_PARAM = bindparam(
    "backoff", value=list(_BACKOFF_SECONDS), type_=ARRAY(Integer)
)

#: Namespace for deterministic envelope ids. Fixed forever: changing it would
#: make every in-flight batch look new to a receiver deduping on event_id.
_EVENT_ID_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def _event_id(subscription_id: int, txn_id: int) -> str:
    """Same batch, same id — on any replica, on any retry."""
    return str(uuid.uuid5(_EVENT_ID_NAMESPACE, f"{subscription_id}:{txn_id}"))


def _event_type(row: EventOutbox) -> str:
    return f"{row.resource_type}.{row.action}"


@dataclass(frozen=True)
class InstallReach:
    """What an installed app may hear right now, for a subscription it holds.

    Read with the subscription roster, in the same statement, once per pass:
    whether the install is live, the initiatives it is placed in, and the
    resources the seat's grant lets it read (writing implies reading).
    """

    live: bool
    placed: frozenset[int]
    readable: frozenset[str]

    @classmethod
    def from_row(
        cls,
        *,
        live: bool | None,
        placed: Iterable[int] | None,
        granted_scopes: Iterable[str] | None,
    ) -> "InstallReach":
        readable: set[str] = set()
        for scope in granted_scopes or ():
            # A scope the vocabulary no longer has grants nothing.
            try:
                read, _write = expand([scope])
            except UnknownAppScope:
                continue
            readable.update(resource.value for resource in read)
        return cls(
            live=bool(live),
            placed=frozenset(placed or ()),
            readable=frozenset(readable),
        )


def _within_reach(row: EventOutbox, reach: InstallReach) -> bool:
    """Whether an installed app may hear about this change now: it is live,
    placed in the change's initiative (or the change belongs to none), and
    holds the read scope of what changed."""
    if not reach.live:
        return False
    if row.initiative_id is not None and row.initiative_id not in reach.placed:
        return False
    resource = webhook_events.read_scope_for(_event_type(row))
    return resource is not None and resource.value in reach.readable


def _matches(
    row: EventOutbox,
    subscription: WebhookSubscription,
    reach: InstallReach | None = None,
) -> bool:
    """Whether one change-item belongs in this subscription's batch.

    Applied per item BEFORE the batch is assembled, so a column filter costs a
    set intersection and no request, and grouping by transaction never widens
    what a subscription receives.

    A subscription an installed app registered also answers to the app's
    reach (:class:`InstallReach`): its declared scope, capped by where the app
    is placed and what it is granted now. ``reach`` is ``None`` only for a
    subscription no app registered.
    """
    if _event_type(row) not in subscription.event_types:
        return False
    if subscription.app_install_id is not None and (
        reach is None or not _within_reach(row, reach)
    ):
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
    subscription: WebhookSubscription,
    txn_id: int,
    rows: list[EventOutbox],
    *,
    guild_ref: str,
    actor_ref: str | None,
    actor_app: str | None = None,
) -> dict[str, Any]:
    """One transaction's matching rows as a single envelope.

    Carries identifiers and changed column NAMES only. A consumer reads current
    state back through the REST API, where the gates apply to the read.

    The guild and the actor arrive already named for this subscriber — minted
    by the caller, which is where the session is. Everything else is a
    per-guild-schema id, which says nothing without the guild;
    ``subscription_id`` included, and that one is what a receiver matches a
    delivery to its own record by.

    ``actor_app`` is the ``public_id`` of the app whose request wrote the
    change, so an app can recognise its own writes. It is set independently of
    ``actor_ref``: an app acting as its community names no person.
    """
    first = rows[0]
    return {
        "event_id": _event_id(subscription.id, txn_id),
        "subscription_id": subscription.id,
        "guild_ref": guild_ref,
        "actor_ref": actor_ref,
        "actor_app": actor_app,
        "occurred_at": first.occurred_at.isoformat(),
        "changes": [
            {
                "event_type": _event_type(row),
                "initiative_id": row.initiative_id,
                "resource": {"type": row.resource_type, "id": row.resource_id},
                # The addressable resources between that one and the
                # initiative, innermost first. Identifiers only, read back
                # through the routes that serve them.
                "parents": list(row.parents),
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

    This runs as the system login with BYPASSRLS (``_drain_subscription``
    routes it so), which is what keeps it a two-column scan of the log rather
    than a policy evaluation per row. It therefore names transactions the
    owner may see nothing of; the per-transaction read that follows, in the
    owner's context, is where that is decided.
    """
    rows = await session.exec(
        text(
            "SELECT o.txn_id "
            "FROM event_outbox o "
            "WHERE pg_visible_in_snapshot(o.txn_id::text::xid8, pg_current_snapshot()) "
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM webhook_deliveries d "
            "    WHERE d.subscription_id = :sid AND d.txn_id = o.txn_id "
            "      AND (d.delivered_at IS NOT NULL OR d.dead_lettered_at IS NOT NULL "
            "           OR d.next_attempt_at > :now)"
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
            "    AND webhook_deliveries.dead_lettered_at IS NULL "
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
) -> tuple[bool, datetime | None]:
    """Record the outcome. Returns whether this call dead-lettered the batch,
    and when a refused batch is next tried.

    ``delivered_at IS NULL`` in the predicate keeps a pass whose lease lapsed
    mid-flight from reopening a batch another pass has already completed.

    A refusal past the last backoff step dead-letters instead of scheduling
    another retry at the final interval forever — computed in the same
    statement that increments ``attempts``, for the same reason the interval
    itself is: two passes racing must not each read a stale count and disagree
    on whether this is the step that ends retries.
    """
    if accepted:
        statement = text(
            "UPDATE webhook_deliveries "
            "SET delivered_at = :now, next_attempt_at = NULL "
            "WHERE subscription_id = :sid AND txn_id = :txn AND delivered_at IS NULL "
            "RETURNING false, NULL::timestamptz"
        ).bindparams(now=now, sid=subscription.id, txn=txn_id)
    else:
        statement = text(
            "UPDATE webhook_deliveries "
            "SET attempts = attempts + 1, "
            "    next_attempt_at = CASE "
            "      WHEN attempts + 1 > cardinality(CAST(:backoff AS integer[])) THEN NULL "
            "      ELSE :now + make_interval(secs => "
            "        (CAST(:backoff AS integer[]))[attempts + 1]) "
            "    END, "
            "    dead_lettered_at = CASE "
            "      WHEN attempts + 1 > cardinality(CAST(:backoff AS integer[])) THEN :now "
            "      ELSE NULL "
            "    END "
            "WHERE subscription_id = :sid AND txn_id = :txn AND delivered_at IS NULL "
            "RETURNING dead_lettered_at IS NOT NULL, next_attempt_at"
        ).bindparams(_BACKOFF_PARAM, now=now, sid=subscription.id, txn=txn_id)
    result = await session.exec(statement)
    row = result.first()
    await session.commit()
    return (bool(row[0]), row[1]) if row is not None else (False, None)


async def _drain_subscription(
    session: AsyncSession,
    subscription: WebhookSubscription,
    *,
    guild_id: int,
    now: datetime,
    reach: InstallReach | None = None,
    app_ids: Mapping[str, str] | None = None,
) -> None:
    """Deliver one subscription's pending transactions, within its own scope.

    What this subscription may be told is ``_matches``: its event types, its
    column filter, and the initiative it names. Nothing reads an account's
    standing, because a subscription has no account — see the module docstring
    for why the scope is the decision.

    Two contexts, and the split is about privilege rather than authorization.
    The candidate scan runs as the system login, because under a guild role
    every row of the log goes through ``initiative_access()`` before the cheap
    filters get a look, and the scan touches the whole log every pass to find
    the handful still owed: measured 3.5s a scan against 1.7ms, on the same
    rows. That login is granted exactly what the scan reads and no more —
    ``SELECT (id, txn_id)`` on the log and five ledger columns, in
    ``SYSTEM_GUILD_MAINTENANCE_GRANTS`` — so the work below, which reads what a
    row says and writes the ledger, routes into the guild's own role for it.

    Routed with ``guild_id`` alone: a poller is not anybody, so it carries no
    user and no role, and the policies admit it by the connection's own login.

    ``reach`` is what the app that registered this subscription may hear, read
    with the roster; ``app_ids`` maps an install's ``listing_uid`` to its
    registration's ``public_id``, for naming the app that wrote a change.
    Transactions outside the reach are settled like any other non-match, so
    they are not delivered later either.
    """
    await set_system_guild_context(session, guild_id=guild_id)
    pending = await _pending_transactions(session, subscription, now=now)

    await set_rls_context(session, guild_id=guild_id)

    for txn_id in pending:
        if not await _claim(session, subscription, txn_id, now=now):
            continue

        # The writing app's listing rides along with each row, so naming it
        # costs no statement of its own.
        rows = list(
            await session.exec(
                select(EventOutbox, GuildApp.listing_uid)
                .outerjoin(GuildApp, GuildApp.id == EventOutbox.actor_install_id)
                .where(EventOutbox.txn_id == txn_id)
                .order_by(EventOutbox.id.asc())
            )
        )
        matched = [
            (row, listing_uid)
            for row, listing_uid in rows
            if _matches(row, subscription, reach)
        ]
        batch = [row for row, _listing_uid in matched]
        if not batch:
            # Nothing in this transaction was for this subscriber. Record it so
            # it is not reconsidered every pass; no request was made, so nothing
            # is claimed about the target.
            await _settle(session, subscription, txn_id, now=now, accepted=True)
            continue

        # One transaction, one actor — the batch is what a single request
        # touched. Named for this subscriber, in the sector its install or its
        # own registration gives it.
        actor_id = batch[0].actor_user_id
        actor_listing = matched[0][1]
        actor_app = (
            None
            if batch[0].actor_install_id is None or actor_listing is None
            else (app_ids or {}).get(actor_listing)
        )
        guild_ref, actor_refs = await webhook_refs.name_for_subscriber(
            guild_id=guild_id,
            app_install_id=subscription.app_install_id,
            subscription_id=subscription.id,
            actor_ids=() if actor_id is None else (actor_id,),
        )

        accepted = await deliver(
            target_url=subscription.target_url,
            secret=subscription.hmac_secret,
            envelope=_envelope(
                subscription,
                txn_id,
                batch,
                guild_ref=guild_ref,
                actor_ref=None if actor_id is None else actor_refs[actor_id],
                actor_app=actor_app,
            ),
        )
        dead_lettered, retry_at = await _settle(
            session, subscription, txn_id, now=now, accepted=accepted
        )
        if dead_lettered:
            logger.warning(
                "webhook delivery dead-lettered: subscription=%s txn=%s target=%s",
                subscription.id,
                txn_id,
                subscription.target_url,
            )
        elif not accepted:
            if retry_at is not None:
                # A retry due before the minute pass would come round is
                # woken for, so the first backoff steps keep their timing.
                delay = (retry_at - now).total_seconds()
                if delay < RETRY_WAKE_WITHIN_SECONDS:
                    asyncio.get_running_loop().call_later(delay, drain.wake, guild_id)
            # Deliver in order: hold the rest of this subscription's backlog
            # until the refused batch gets through. Once dead-lettered there is
            # nothing left to wait on, so later transactions proceed instead of
            # queuing behind a batch that will never be retried again.
            return


def _roster(live_listings: Iterable[str]):
    """The active subscriptions, each with what its app may hear right now.

    One statement for the whole guild. A subscription an app registered is
    joined to its install: live when the install is enabled and its
    registration is (``live_listings``, the listings of the live registrations,
    by the rule the install standing reads), the initiatives it is
    placed in, and the scopes its seat granted. A subscription no app
    registered carries NULLs there and is not asked about any of it.
    """
    placed = (
        select(func.array_agg(AppPlacement.initiative_id))
        .where(AppPlacement.install_id == WebhookSubscription.app_install_id)
        .scalar_subquery()
    )
    live = and_(
        GuildApp.enabled.is_(True),
        GuildApp.listing_uid.in_(sorted(set(live_listings))),
    )
    return (
        select(
            WebhookSubscription.id,
            WebhookSubscription.app_install_id,
            live.label("live"),
            placed.label("placed"),
            GuildApp.granted_scopes,
        )
        .outerjoin(GuildApp, GuildApp.id == WebhookSubscription.app_install_id)
        .where(
            WebhookSubscription.active.is_(True),
            # The rule ``registered_install_is_live`` states for the
            # dispatcher, read off the join: an install that is gone is
            # drained to nobody.
            or_(
                WebhookSubscription.app_install_id.is_(None),
                GuildApp.id.is_not(None),
            ),
        )
        .order_by(WebhookSubscription.id.asc())
    )


#: Communities with an active subscription, as this process last read them.
#: The minute pass's visit keeps it current, and a subscription changing
#: wakes the drain, whose visit does the same.
_subscribed: set[int] = set()

#: Communities whose log moved and which have somebody to deliver it to.
drain = Drain("outbox", settle=DRAIN_SETTLE_SECONDS)


async def hint(payload: str) -> None:
    """A committed transaction wrote to a community's log. Registered on the
    capture's channel beside the room sink; a community with no active
    subscription is left alone."""
    schema, _, _txn = payload.partition(":")
    guild_id = room_sink.schema_guild_id(schema)
    if guild_id in _subscribed:
        drain.wake(guild_id)


def subscriptions_changed(guild_id: int) -> None:
    """A subscription in the community was created, enabled or deleted. Its
    visit reads the roster again, and settles whether it stays in
    :data:`_subscribed`."""
    _subscribed.add(guild_id)
    drain.wake(guild_id)


async def drain_guild(
    session: AsyncSession, guild_id: int, *, now: datetime | None = None
) -> None:
    """Deliver what the community's subscriptions are owed."""
    now = now or datetime.now(timezone.utc)
    # Read the subscription roster with full guild authority: which targets are
    # registered is guild configuration, not initiative content. What each of
    # them may then SEE is decided per subscription in _drain_subscription:
    # the scope it names and, for one an app registered, the app's reach.
    registrations = (await load_registrations()).values()
    app_ids = {r.listing_uid: r.public_id for r in registrations if r.listing_uid}
    live_listings = [r.listing_uid for r in registrations if r.listing_uid and r.live]
    await set_rls_context(session, guild_id=guild_id)
    # Ids, not instances: each pass ends by expunging the identity map (ids
    # repeat across guild schemas), and an instance held across that is detached.
    roster = [
        (
            row.id,
            None
            if row.app_install_id is None
            else InstallReach.from_row(
                live=row.live, placed=row.placed, granted_scopes=row.granted_scopes
            ),
        )
        for row in await session.exec(_roster(live_listings))
    ]
    if roster:
        _subscribed.add(guild_id)
    else:
        _subscribed.discard(guild_id)
    for subscription_id, reach in roster:
        try:
            subscription = await session.get(WebhookSubscription, subscription_id)
            if subscription is None or not subscription.active:
                continue
            await _drain_subscription(
                session,
                subscription,
                guild_id=guild_id,
                now=now,
                reach=reach,
                app_ids=app_ids,
            )
        except Exception:
            logger.exception(
                "outbox drain failed: guild=%s subscription=%s",
                guild_id,
                subscription_id,
            )
            await session.rollback()
        finally:
            session.expunge_all()
            await set_rls_context(session, guild_id=guild_id)


async def expire_history(session: AsyncSession, guild_id: int) -> None:
    """Drop the community's outbox history, and the ledger rows referencing
    it, past the window.

    Age-based on purpose: a subscription weeks behind is broken, and holding the
    log open for it would grow the table without bound on every instance that
    never configures a target at all. Ledger rows go with the events they
    describe, so the pair stays the same size.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=OUTBOX_RETENTION_DAYS)
    stale = list(
        await session.exec(select(EventOutbox).where(EventOutbox.occurred_at < cutoff))
    )
    if not stale:
        return
    txn_ids = sorted({row.txn_id for row in stale})
    for row in stale:
        await session.delete(row)
    await session.exec(
        text("DELETE FROM webhook_deliveries WHERE txn_id = ANY(:txn_ids)").bindparams(
            txn_ids=txn_ids
        )
    )
    logger.info("outbox retention: guild=%s removed=%s", guild_id, len(stale))
