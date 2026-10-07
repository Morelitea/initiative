"""Ending a connection's grant at the vendor.

Deleting our copy is the authoritative half of ending access: the platform
will never hand the plug-in a token for that credential again. It is not the whole
of it, because the grant is still live at the vendor until somebody ends it.
Initiative holds the grant for every connection whose flow it ran, so it ends
it too, the way the connection's manifest says (``flow.revoke``):

* ``rfc7009`` — a revocation request to the vendor's ``revoke_url`` (RFC 7009),
  with the vendor client's credentials;
* ``github_grant`` — a ``DELETE`` to GitHub's grant address (``revoke_url``),
  with the vendor client's credentials and the access token;
* ``hook`` — the plug-in's revoke hook, with the tokens, for a vendor whose
  revocation the plug-in knows how to ask for;
* absent — the tokens are deleted and nothing is sent.

Two properties this module keeps:

* **Captured during the transaction, sent after it.** An intent carries the
  sealed tokens of the row it ends, read before the row is deleted, and is
  queued on the session's commit (:func:`app.db.post_commit.after_commit`), so
  a rolled-back delete, or one in a rolled-back savepoint, never ends a grant.
* **Never able to fail a teardown.** Each intent is tried three times and a
  failure is logged. A member who left a community has left it whether or not
  the vendor answered.

A transaction's intents are sent together once it commits, several at a
time, since each is its own vendor round trip with its own tries. They run as a
task of their own, so a request's answer does not wait on the vendors; a caller
that must know they have gone awaits :func:`app.db.post_commit.settle`.

Every path that deletes a connection's stored values queues an intent here,
whether or not the connection declares a way to revoke it, so each ending is
logged in one place.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

from app.db import post_commit
from app.db.session import routed_guild_id
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.marketplace import registration_lookup
from app.services.marketplace.registration_lookup import (
    is_declarative,
    service_public_id,
)
from app.services.tenant.plugin_config import RESERVED_TOKEN_KEYS, without_tokens

logger = logging.getLogger(__name__)

__all__ = [
    "REVOKE_ATTEMPTS",
    "RevocationIntent",
    "dispatch_revocations",
    "queue_install_revocations",
    "queue_revocations_for_rows",
]

_STEP_KEY = "plugin_credential_revocations"

#: How many times one revocation is sent before it is logged and dropped.
REVOKE_ATTEMPTS = 3
#: The pause before the second and third tries, in seconds.
retry_delays: tuple[float, ...] = (0.5, 1.0)
#: How many intents are sent at once.
REVOKE_CONCURRENCY = 8


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
    plugin_id: int
    listing_uid: str
    connection_id: str
    connection_ref: Optional[str] = None
    user_id: Optional[int] = None
    reason: str = "revoked"
    public_id: Optional[str] = None
    #: The plug-in is declarative, and is named by its listing.
    declarative: bool = False
    flow: Optional[dict[str, Any]] = None
    fields: dict[str, Any] = field(default_factory=dict)
    sealed_tokens: dict[str, str] = field(default_factory=dict)
    #: When the stored access token lapses, from the connection's values.
    expires_at: Optional[int] = None


def _intent_for(
    *,
    guild_id: int,
    plugin_id: int,
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
        plugin_id=plugin_id,
        listing_uid=listing_uid,
        connection_id=connection_id,
        connection_ref=connection_ref,
        user_id=user_id,
        reason=reason,
        public_id=service_public_id(definition),
        declarative=is_declarative(definition),
        flow=dict(flow) if isinstance(flow, dict) else None,
        fields=without_tokens(config),
        sealed_tokens={
            key: value
            for key, value in (secrets or {}).items()
            if key in RESERVED_TOKEN_KEYS and isinstance(value, str)
        },
        expires_at=(
            expiry
            if isinstance(expiry := (config or {}).get("expires_at"), int)
            and not isinstance(expiry, bool)
            else None
        ),
    )


class _Revocations(list[RevocationIntent]):
    """One transaction's intents, sent together once it commits."""

    def join(self, released: list[RevocationIntent]) -> None:
        """Take a released savepoint's intents."""
        self.extend(released)

    def __call__(self) -> Awaitable[None]:
        return dispatch_revocations(self)


def _queue(session: Any, intent: RevocationIntent) -> None:
    """Record one intent, to be sent once the caller commits."""
    post_commit.after_commit(session, _Revocations(), key=_STEP_KEY).append(intent)


def queue_install_revocations(
    session: Any,
    plugin: GuildPlugin,
    connection_ids: Iterable[str],
    *,
    secrets: Mapping[str, Any],
    reason: str,
) -> None:
    """Record an intent for each of ``plugin``'s community connections whose
    stored values are about to go.

    Read from ``plugin.config``, ``secrets`` and ``plugin.definition`` as they are,
    so it is called before any of them changes.
    """
    guild_id = routed_guild_id(session)
    for connection_id in sorted(connection_ids):
        _queue(
            session,
            _intent_for(
                guild_id=guild_id,
                plugin_id=plugin.id,
                listing_uid=plugin.listing_uid,
                definition=plugin.definition,
                connection_id=connection_id,
                config=(plugin.config or {}).get(connection_id),
                secrets=secrets.get(connection_id),
                reason=reason,
            ),
        )


def queue_revocations_for_rows(
    session: Any,
    rows: Iterable[Any],
    *,
    reason: str,
    installs: Mapping[int, tuple[str, Mapping[str, Any] | None]],
) -> None:
    """Record an intent for each member connection row whose values are about
    to go. ``installs`` gives, per install id, its listing and the definition
    its connections were made under."""
    guild_id = routed_guild_id(session)
    for row in rows:
        listing_uid, definition = installs.get(row.plugin_id, ("", None))
        _queue(
            session,
            _intent_for(
                guild_id=guild_id,
                plugin_id=row.plugin_id,
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


async def dispatch_revocations(intents: list[RevocationIntent]) -> None:
    """Send queued intents, several at a time. Best-effort, and never raises."""
    limit = asyncio.Semaphore(REVOKE_CONCURRENCY)

    async def bounded(intent: RevocationIntent) -> None:
        async with limit:
            await _dispatch_one(intent)

    await asyncio.gather(*(bounded(intent) for intent in intents))


async def _dispatch_one(intent: RevocationIntent) -> None:
    logger.info(
        "plug-in credential revoked: guild=%s plug-in=%s listing=%s connection=%s "
        "ref=%s reason=%s",
        intent.guild_id,
        intent.plugin_id,
        intent.listing_uid,
        intent.connection_id,
        intent.connection_ref or "-",
        intent.reason,
    )
    try:
        await _deliver(intent)
    except Exception:
        logger.exception(
            "plug-in credential revocation: guild=%s plug-in=%s connection=%s failed",
            intent.guild_id,
            intent.plugin_id,
            intent.connection_id,
        )


async def _deliver(intent: RevocationIntent) -> None:
    """End one grant the way its flow says, with three tries."""
    method = (intent.flow or {}).get("revoke")
    if method not in ("rfc7009", "github_grant", "hook") or not intent.sealed_tokens:
        return
    if intent.public_id is None and intent.declarative:
        # A declarative plug-in is its listing's: the registration that listing
        # applied names it.
        registration = await registration_lookup.declarative_registration(
            intent.listing_uid
        )
        if registration is not None:
            intent = replace(intent, public_id=registration.public_id)
    if not intent.public_id:
        logger.info(
            "plug-in credential revocation: plug-in %s names no service; dropped",
            intent.plugin_id,
        )
        return

    # Imported here: the flow module reads connection rows, whose own module
    # queues intents here.
    from app.services.tenant import plugin_connection_flows as flows

    try:
        send = await flows.revocation_sender(
            method=method,
            public_id=intent.public_id,
            flow=intent.flow or {},
            fields=intent.fields,
            sealed_tokens=intent.sealed_tokens,
            guild_id=intent.guild_id,
            install_id=intent.plugin_id,
            connection_id=intent.connection_id,
            expires_at=intent.expires_at,
        )
    except flows.ConnectionFlowError as exc:
        logger.warning(
            "plug-in credential revocation: plug-in %s connection %s cannot be sent (%s); "
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
                    "plug-in credential revocation: plug-in %s connection %s was not "
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
