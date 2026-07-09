"""Fire-and-forget membership-change ping to the external billing service.

Seats are event-driven (write-boundary plan D5): when a guild's membership
changes, billing is nudged to re-read the authoritative headcount via its
signed ``/billing/headcount`` call and push recomputed caps back through
``/billing/guild-tier``. The ping is a **trigger, not a source of truth**:

* payload is the guild id and a fresh event id only — no member data, no
  PII, and deliberately **no member count** (a forged or stale ping can only
  cause billing to recompute the truth);
* no retry queue and no delivery guarantee — a lost ping is corrected by
  the next one or by billing's period-close reconciliation;
* the join/leave transaction must never fail or slow because billing is
  down: the send runs as a detached task with a tight timeout and swallows
  every error.

FOSS balance: on a self-hosted install (``BILLING_SERVICE_URL`` /
``BILLING_HMAC_SECRET`` unset — the default) :func:`notify_membership_changed`
returns before doing anything: no outbound call, no queued work, no logging.

The request carries the same request-bound HMAC discipline as the inbound
envelope (``METHOD\\nPATH\\nTIMESTAMP\\nsha256(body)`` keyed by the shared
secret), so billing can authenticate the nudge without a second credential.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

MEMBERSHIP_PING_PATH = "/api/v1/pings/membership"

# httpx defaults to no total deadline; keep the whole attempt short — the
# ping is advisory and must never hold resources behind a slow billing pod.
_PING_TIMEOUT = httpx.Timeout(3.0, connect=2.0)

# Strong references so in-flight pings aren't garbage-collected mid-send
# (asyncio keeps only weak refs to tasks).
_pending_pings: set[asyncio.Task] = set()


def billing_ping_enabled() -> bool:
    """True only when a hosted deployment configured the outbound side."""
    return bool(settings.BILLING_SERVICE_URL and settings.BILLING_HMAC_SECRET)


def build_membership_ping(guild_id: int) -> tuple[str, bytes, dict[str, str]]:
    """Assemble (url, body, headers) for one ping. Pure — no I/O.

    The HMAC is bound to the path component billing's verifier will see,
    so a base URL with a path prefix still signs correctly.
    """
    base = settings.BILLING_SERVICE_URL.rstrip("/")
    url = base + MEMBERSHIP_PING_PATH
    path = urlsplit(url).path
    body = json.dumps(
        {"guild_id": int(guild_id), "event_id": uuid4().hex},
        separators=(",", ":"),
    ).encode()
    ts = str(int(time.time()))
    message = "\n".join(["POST", path, ts, hashlib.sha256(body).hexdigest()]).encode()
    signature = hmac.new(
        settings.BILLING_HMAC_SECRET.encode(), message, hashlib.sha256
    ).hexdigest()
    headers = {
        "X-Billing-Timestamp": ts,
        "X-Billing-Signature": signature,
        "Content-Type": "application/json",
    }
    return url, body, headers


async def _send_membership_ping(guild_id: int) -> None:
    """One attempt, no retry; never raises (task exceptions would only spam
    the loop's never-retrieved handler)."""
    try:
        url, body, headers = build_membership_ping(guild_id)
        async with httpx.AsyncClient(timeout=_PING_TIMEOUT) as client:
            await client.post(url, content=body, headers=headers)
    except Exception:
        logger.debug(
            "billing: membership ping for guild %s failed (billing will "
            "reconcile at period close)",
            guild_id,
        )


def notify_membership_changed(guild_id: int) -> None:
    """Nudge billing that ``guild_id``'s membership changed.

    Call from any code path that inserts or deletes a ``guild_memberships``
    row. Fire-and-forget: returns immediately, and is a complete no-op when
    billing is not configured. Callers may invoke this before their commit —
    a ping for a rolled-back change is harmless because billing re-reads the
    committed headcount, never the ping.
    """
    if not billing_ping_enabled():
        return
    task = asyncio.create_task(_send_membership_ping(int(guild_id)))
    _pending_pings.add(task)
    task.add_done_callback(_pending_pings.discard)
