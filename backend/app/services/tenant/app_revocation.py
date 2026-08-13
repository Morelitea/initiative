"""Telling an app that a credential it holds is finished.

Deleting our copy is the authoritative half of ending access — the platform
will never hand the app a caller for that credential again. It is not the whole
of it: the app obtained tokens under this guild's authority and may have
registered webhooks with the vendor, and those keep working until somebody says
otherwise. So every path that deletes stored values also records a revocation,
addressed by the same opaque ``connection_ref`` the app knows the credential by.

Two properties this module exists to keep:

* **Recorded during the transaction, delivered after it.** Intents are queued on
  the session while the deletes happen and drained by the caller once the
  transaction has committed. Telling an app to forget a credential and then
  rolling back the delete would leave the two sides disagreeing in the dangerous
  direction.
* **Never able to fail a teardown.** Delivery is best-effort. A member who left
  a guild has left it whether or not the app acknowledged; an unreachable app
  converges on its next reconciliation pull, because the install it is
  reconciling against no longer offers that connection.

The transport belongs to the app protocol: an intent is addressed to a listing,
a connection, and a ref, and the registration that carries a base URL and a
signing secret is what turns that into a request. Until that lands the queue
drains to the log, which is deliberately the only thing that changes when the
transport arrives — every teardown path is already wired through here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "RevocationIntent",
    "drain_revocations",
    "dispatch_revocations",
    "queue_revocation",
    "queue_revocations_for_rows",
]

_SESSION_INFO_KEY = "app_credential_revocations"


@dataclass(frozen=True)
class RevocationIntent:
    """One credential an app should stop using.

    ``connection_ref`` is absent for a guild-scoped credential: those are not
    addressed per person, so the app is told which install and connection
    instead. ``user_id`` is carried for the audit line only and is never part of
    what the app is sent — an app addresses people by ref precisely so it never
    holds one of our user ids.
    """

    guild_id: int
    app_id: int
    listing_uid: str
    connection_id: str
    connection_ref: Optional[str] = None
    user_id: Optional[int] = None
    reason: str = "revoked"


def queue_revocation(session: Any, intent: RevocationIntent) -> None:
    """Record one intent, to be delivered after the caller commits."""
    session.info.setdefault(_SESSION_INFO_KEY, []).append(intent)


def queue_revocations_for_rows(
    session: Any, *, listing_uid: str, rows: Any, reason: str
) -> None:
    """Record an intent for each per-member connection row being deleted."""
    for row in rows:
        queue_revocation(
            session,
            RevocationIntent(
                guild_id=row.guild_id,
                app_id=row.app_id,
                listing_uid=listing_uid,
                connection_id=row.connection_id,
                connection_ref=row.connection_ref,
                user_id=row.user_id,
                reason=reason,
            ),
        )


def drain_revocations(session: Any) -> list[RevocationIntent]:
    """Take (and clear) the queued intents. Call after commit."""
    return session.info.pop(_SESSION_INFO_KEY, [])


async def dispatch_revocations(intents: list[RevocationIntent]) -> None:
    """Deliver queued intents. Best-effort, and never raises.

    The delivery itself arrives with the app protocol's signed channel; what is
    already true is that every intent reaches here, so nothing has to be
    rediscovered later.
    """
    for intent in intents:
        logger.info(
            "app credential revoked: guild=%s app=%s listing=%s connection=%s "
            "ref=%s reason=%s",
            intent.guild_id,
            intent.app_id,
            intent.listing_uid,
            intent.connection_id,
            intent.connection_ref or "-",
            intent.reason,
        )
