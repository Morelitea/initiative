"""Outbound webhook dispatcher.

When something interesting happens (``task.created``,
``task.status_changed``, …), call :func:`dispatch_event` with the event
type, scope, and payload. The dispatcher looks up matching active
subscriptions, builds an envelope, signs it with the subscription's
HMAC secret, and POSTs to the target URL.

Failure handling is intentionally permissive in v0: a subscriber that's
slow or down does NOT block the user write that produced the event.
We log and move on. Retry, dead-letter, and async dispatch (queue
worker) live in PR2.4 once we have observability of how often deliveries
fail.

Verification (the receiver's job, in initiative-auto):

  1. Parse ``X-Initiative-Timestamp`` and reject if older than ~5 min.
  2. Compute HMAC-SHA256 over ``timestamp + "." + body`` with the
     subscription's stored secret.
  3. Compare to ``X-Initiative-Signature`` (constant-time).
  4. Dedup on ``X-Initiative-Event-ID`` so retries don't double-fire.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.marketplace.registration_lookup import any_delegate_registered
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.services.safe_http import request_public_target
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

logger = logging.getLogger(__name__)


_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)

#: Whether this process has already said that dispatch is inert. Every write
#: that produces an event calls the dispatcher, so the explanation is worth
#: saying once per process and never per event.
_inert_logged = False


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over ``timestamp + "." + body`` matching what the
    receiver will compute. The timestamp is included so a resigned
    replay of a captured body fails the signature check (the timestamp
    differs)."""
    mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(timestamp.encode("utf-8"))
    mac.update(b".")
    mac.update(body)
    return f"sha256={mac.hexdigest()}"


async def _deliver(
    *,
    target_url: str,
    secret: str,
    envelope: dict[str, Any],
) -> None:
    """POST one envelope to one target. Logs and swallows any error so
    one bad subscriber can't break the rest of the dispatch.

    Delivery goes through :func:`request_public_target`, which resolves
    the target host once and connects to that validated address. The
    target is re-checked here (not only at create/update time) because a
    hostname's resolution can change between registration and delivery.
    """
    body = json.dumps(envelope, default=str, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    signature = _sign(secret, timestamp, body)

    headers = {
        "Content-Type": "application/json",
        "X-Initiative-Event-ID": envelope["event_id"],
        "X-Initiative-Timestamp": timestamp,
        "X-Initiative-Signature": signature,
        "User-Agent": "initiative-webhooks/1",
    }

    try:
        response = await request_public_target(
            "POST",
            target_url,
            headers=headers,
            content=body,
            timeout=_TIMEOUT,
        )
    except (WebhookTargetUrlError, WebhookTargetUrlPrivateError) as exc:
        logger.warning(
            "webhook delivery skipped — target failed validation: target=%s err=%s",
            target_url,
            exc,
        )
        return
    except Exception as exc:  # noqa: BLE001 — best-effort delivery
        logger.warning(
            "webhook delivery failed: target=%s event=%s err=%s",
            target_url,
            envelope["event_type"],
            exc,
        )
        return

    if response.status_code >= 400:
        logger.warning(
            "webhook delivery non-2xx: target=%s event=%s status=%s",
            target_url,
            envelope["event_type"],
            response.status_code,
        )


async def dispatch_event(
    session: AsyncSession,
    *,
    event_type: str,
    guild_id: int,
    payload: dict[str, Any],
    initiative_id: int | None = None,
) -> None:
    """Find matching subscriptions and POST the event to each.

    Matches require:
      * subscription.guild_id == event guild_id (RLS already enforces)
      * subscription.event_types includes event_type
      * subscription.active is true
      * subscription.initiative_id is None OR equal to event initiative_id
        (a guild-scoped subscription matches initiative-scoped events too,
        which is the right semantics — guild-scoped means "any event in
        the guild")

    Deliveries fan out concurrently. Caller's request is awaited until
    all deliveries return or time out (5s each). For v0 that latency is
    acceptable because the typical case is zero or one subscriber.
    Move to a background queue when delivery counts climb.

    With no automation delegate configured this returns immediately: the
    delegate owns delivery targets, so on such a deployment there are none to
    deliver to. Returning before the query keeps the cost of the feature at
    zero on the write path rather than one query per event.
    """
    if not await any_delegate_registered():
        global _inert_logged
        if not _inert_logged:
            _inert_logged = True
            logger.info(
                "webhook dispatch inert: no delegate registered "
                "(grant an app service the delegation power and provision the "
                "keys it signs with)"
            )
        return

    statement = select(WebhookSubscription).where(
        WebhookSubscription.guild_id == guild_id,
        WebhookSubscription.active.is_(True),
        WebhookSubscription.event_types.contains([event_type]),
    )
    if initiative_id is not None:
        # ``initiative_id IS NULL OR initiative_id = :initiative_id``
        # — guild-wide subs always match, initiative-scoped only when
        # they match the event's initiative.
        statement = statement.where(
            (WebhookSubscription.initiative_id.is_(None))
            | (WebhookSubscription.initiative_id == initiative_id)
        )
    else:
        # No initiative_id on the event → only guild-scoped subs match.
        statement = statement.where(WebhookSubscription.initiative_id.is_(None))

    rows = (await session.exec(statement)).all()
    if not rows:
        return

    envelope_base = {
        "event_type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "guild_id": guild_id,
        "initiative_id": initiative_id,
        "payload": payload,
    }

    # Per-subscription envelope copies. Each delivery gets a fresh
    # ``event_id`` so a receiver dedup-ing on that header doesn't drop
    # legitimate fan-out to multiple subscriptions of the same logical
    # event, and so future per-target retry logic can dedup retries
    # without colliding across subscriptions. ``subscription_id`` and
    # ``workflow_id`` are included for the receiver's routing.
    deliveries: list[asyncio.Task] = []
    for sub in rows:
        envelope = {
            **envelope_base,
            "event_id": str(uuid.uuid4()),
            "subscription_id": sub.id,
            "workflow_id": sub.workflow_id,
        }
        deliveries.append(
            asyncio.create_task(
                _deliver(
                    target_url=sub.target_url,
                    secret=sub.hmac_secret,
                    envelope=envelope,
                )
            )
        )

    # Wait for all to complete; ``_deliver`` swallows its own errors so
    # ``return_exceptions=True`` is just belt-and-suspenders.
    await asyncio.gather(*deliveries, return_exceptions=True)
