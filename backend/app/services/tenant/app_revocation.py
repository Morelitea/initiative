"""Ending a connection's grant at the vendor.

Deleting our copy is the authoritative half of ending access: the platform
will never hand the app a token for that credential again. It is not the whole
of it, because the grant is still live at the vendor until somebody ends it.
Initiative holds the grant for every connection whose flow it ran, so it ends
it too, the way the connection's manifest says (``flow.revoke``):

* ``rfc7009`` — a revocation request to the vendor's ``revoke_url`` (RFC 7009),
  with the vendor client's credentials;
* ``hook`` — the app's revoke hook, with the tokens, for a vendor whose
  revocation the app knows how to ask for;
* absent — the tokens are deleted and nothing is sent.

Two properties this module keeps:

* **Captured during the transaction, sent after it.** An intent carries the
  sealed tokens of the row it ends, read before the row is deleted, and is
  queued on the session. The caller drains the queue once the transaction has
  committed, so a rolled-back delete never ends a grant.
* **Never able to fail a teardown.** Each intent is tried three times and a
  failure is logged. A member who left a community has left it whether or not
  the vendor answered.

Every path that deletes a connection's stored values queues an intent here,
whether or not the connection declares a way to revoke it, so each ending is
logged in one place.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional

from app.db.session import routed_guild_id

logger = logging.getLogger(__name__)

__all__ = [
    "REVOKE_ATTEMPTS",
    "RevocationIntent",
    "dispatch_revocations",
    "drain_revocations",
    "intent_for",
    "queue_revocation",
    "queue_revocations_for_rows",
]

_SESSION_INFO_KEY = "app_credential_revocations"

#: How many times one revocation is sent before it is logged and dropped.
REVOKE_ATTEMPTS = 3
#: The pause before the second and third tries, in seconds.
retry_delays: tuple[float, ...] = (0.5, 1.0)

#: The keys a flow's sealed tokens are held under.
_SEALED_KEYS = ("access_token", "refresh_token")


@dataclass(frozen=True)
class RevocationIntent:
    """One grant to end.

    ``connection_ref`` is absent for a community connection, which is not
    addressed per person. ``user_id`` is carried for the log line only.

    ``flow`` is the connection's declared flow as the install had it, ``fields``
    its plain stored values (what a ``revoke_url`` template may name), and
    ``sealed_tokens`` its tokens as they were stored, still sealed. All three
    are captured before the row is deleted.
    """

    guild_id: int
    app_id: int
    listing_uid: str
    connection_id: str
    connection_ref: Optional[str] = None
    user_id: Optional[int] = None
    reason: str = "revoked"
    public_id: Optional[str] = None
    flow: Optional[dict[str, Any]] = None
    fields: dict[str, Any] = field(default_factory=dict)
    sealed_tokens: dict[str, str] = field(default_factory=dict)


def _public_id(definition: Mapping[str, Any] | None) -> Optional[str]:
    service = (definition or {}).get("service")
    if isinstance(service, dict) and isinstance(service.get("public_id"), str):
        return service["public_id"]
    return None


def intent_for(
    *,
    guild_id: int,
    app_id: int,
    listing_uid: str,
    definition: Mapping[str, Any] | None,
    connection_id: str,
    config: Mapping[str, Any] | None,
    secrets: Mapping[str, Any] | None,
    reason: str,
    connection_ref: Optional[str] = None,
    user_id: Optional[int] = None,
) -> RevocationIntent:
    """An intent for one connection's stored values, read before they go."""
    connection = None
    for entry in (definition or {}).get("connections") or []:
        if isinstance(entry, dict) and entry.get("id") == connection_id:
            connection = entry
            break
    flow = (connection or {}).get("flow")
    return RevocationIntent(
        guild_id=guild_id,
        app_id=app_id,
        listing_uid=listing_uid,
        connection_id=connection_id,
        connection_ref=connection_ref,
        user_id=user_id,
        reason=reason,
        public_id=_public_id(definition),
        flow=dict(flow) if isinstance(flow, dict) else None,
        fields={
            key: value
            for key, value in (config or {}).items()
            if key not in ("expires_at", "refresh_expires_at")
        },
        sealed_tokens={
            key: value
            for key, value in (secrets or {}).items()
            if key in _SEALED_KEYS and isinstance(value, str)
        },
    )


def queue_revocation(session: Any, intent: RevocationIntent) -> None:
    """Record one intent, to be sent after the caller commits."""
    session.info.setdefault(_SESSION_INFO_KEY, []).append(intent)


def queue_revocations_for_rows(
    session: Any,
    *,
    listing_uid: str,
    rows: Any,
    reason: str,
    definition: Mapping[str, Any] | None = None,
) -> None:
    """Record an intent for each member connection row being deleted."""
    for row in rows:
        queue_revocation(
            session,
            intent_for(
                guild_id=routed_guild_id(session),
                app_id=row.app_id,
                listing_uid=listing_uid,
                definition=definition,
                connection_id=row.connection_id,
                config=row.config,
                secrets=row.config_secrets,
                reason=reason,
                connection_ref=row.connection_ref,
                user_id=row.user_id,
            ),
        )


def drain_revocations(session: Any) -> list[RevocationIntent]:
    """Take (and clear) the queued intents. Call after commit."""
    return session.info.pop(_SESSION_INFO_KEY, [])


async def dispatch_revocations(intents: list[RevocationIntent]) -> None:
    """Send queued intents. Best-effort, and never raises."""
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
        try:
            await _deliver(intent)
        except Exception:
            logger.exception(
                "app credential revocation: guild=%s app=%s connection=%s failed",
                intent.guild_id,
                intent.app_id,
                intent.connection_id,
            )


async def _deliver(intent: RevocationIntent) -> None:
    """End one grant the way its flow says, with three tries."""
    method = (intent.flow or {}).get("revoke")
    if method not in ("rfc7009", "hook") or not intent.sealed_tokens:
        return
    if not intent.public_id:
        logger.info(
            "app credential revocation: app %s names no service; dropped",
            intent.app_id,
        )
        return

    # Imported here: the flow module reads connection rows, whose own module
    # queues intents here.
    from app.services.tenant import app_connection_flows as flows

    try:
        send = await flows.revocation_sender(
            method=method,
            public_id=intent.public_id,
            flow=intent.flow or {},
            fields=intent.fields,
            sealed_tokens=intent.sealed_tokens,
            guild_id=intent.guild_id,
            install_id=intent.app_id,
            connection_id=intent.connection_id,
        )
    except flows.ConnectionFlowError as exc:
        logger.warning(
            "app credential revocation: app %s connection %s cannot be sent (%s); "
            "dropped",
            intent.public_id,
            intent.connection_id,
            exc.code,
        )
        return
    if send is None:
        return
    await _with_tries(send, intent)


async def _with_tries(
    send: Callable[[], Awaitable[None]], intent: RevocationIntent
) -> None:
    for attempt in range(REVOKE_ATTEMPTS):
        try:
            await send()
            return
        except Exception as exc:
            if attempt + 1 >= REVOKE_ATTEMPTS:
                logger.warning(
                    "app credential revocation: app %s connection %s was not "
                    "accepted after %s tries (%s)",
                    intent.public_id,
                    intent.connection_id,
                    REVOKE_ATTEMPTS,
                    exc,
                )
                return
            delay = retry_delays[min(attempt, len(retry_delays) - 1)]
            if delay > 0:
                await asyncio.sleep(delay)
