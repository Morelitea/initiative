"""A vendor's webhooks, received for the plug-in that declares them.

A plug-in whose manifest declares ``webhooks`` has one address on this
deployment, ``POST /api/v1/plugin-hooks/{public_id}``, which the operator gives
the vendor. :func:`receive` takes each delivery through four steps:

1. The signature is checked with the registration's vendor secret. A delivery
   that does not verify is refused (401).
2. The route value is read from the delivery wherever a version of the
   listing's ``webhooks.route`` reads it (a path in the JSON body, or a
   header), and each value is matched against the install index
   (:func:`plugin_installs.routed`). An install is matched only when the route
   of the version it is pinned to reads its value. A delivery nothing matches
   is answered 202 and nothing is stored.
3. For each matched install, in its own community and several communities at
   once, read as the version that install is pinned to: a delivery id the
   install has already accepted (``plugin_hook_deliveries``) is skipped.
   Otherwise a container's install has the raw body and the vendor's ``x-``
   headers sent to its ``webhook`` hook with a ``lifecycle`` token naming that
   install, and a 2xx records the id for 24 hours. A declarative plug-in's install
   maps it with its ``events`` and ``status``: the event goes to the outbox as
   a container's emission does, the state to the install's configuration
   state, and the id is recorded with them. A mapping that cannot succeed is
   logged and recorded; one that may succeed if asked again records nothing.
4. 202 when every matched install accepted it or already had; otherwise 503
   when a mapping is to be asked again, or 502, so the vendor's redelivery
   reaches only the ones that did not.

The index row that routes a delivery is written only when a community's
connect stored the routed value, which the plug-in's ``after_connect`` hook
checked at the vendor.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select

from app.core import metrics
from app.db import cohorts
from app.db import session as db_session
from app.db.session import set_rls_context
from app.models.platform.marketplace import (
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.models.tenant.plugin_hook_delivery import (
    DELIVERY_ID_MAX_LENGTH,
    PluginHookDelivery,
)
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.marketplace import plugin_installs, declarative, registration_lookup
from app.services.marketplace.expressions import ExpressionError
from app.services.marketplace.registration_lookup import (
    RegistrationSnapshot,
    is_declarative,
)
from app.services.marketplace.vendor_values import (
    listing_definitions,
    load_vendor_values,
)
from app.services.tenant import plugin_connection_flows as flows
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant.plugin_channels import (
    PluginChannelError,
    keep_event,
    owns_install,
    set_connection_state,
)
from app.services.tenant.plugin_config import without_tokens
from app.db.request_context import SystemGuild

logger = logging.getLogger(__name__)

__all__ = ["DELIVERY_TTL", "receive"]

#: How long an accepted delivery id is remembered.
DELIVERY_TTL = timedelta(hours=24)
#: How many communities one delivery is forwarded to at once.
FORWARD_CONCURRENCY = 8

_DIGESTS = {"hmac_sha256": hashlib.sha256, "hmac_sha1": hashlib.sha1}


def _verified(
    verify: Mapping[str, Any], secret: str, headers: Mapping[str, str], body: bytes
) -> bool:
    """Whether the signature header holds the HMAC of ``body`` under
    ``secret``, as the manifest writes it."""
    digest_of = _DIGESTS.get(str(verify.get("scheme")))
    given = headers.get(str(verify.get("header", "")).lower(), "")
    prefix = str(verify.get("prefix") or "")
    if digest_of is None or not given.startswith(prefix):
        return False
    digest = hmac.new(secret.encode("utf-8"), body, digest_of).digest()
    expected = (
        digest.hex()
        if verify.get("encoding") == "hex"
        else base64.b64encode(digest).decode("ascii")
    )
    return hmac.compare_digest(
        expected.encode("utf-8"), given[len(prefix) :].strip().encode("utf-8")
    )


def _route_value(
    route: Mapping[str, Any], headers: Mapping[str, str], body: bytes
) -> Optional[str]:
    """The value a ``webhooks.route`` reads from a delivery, as the install
    index stores it, or ``None``: the header it names, or the value at its
    ``path`` (keys joined by ``.``) in the JSON body."""
    if "header" in route:
        return headers.get(str(route["header"]).lower()) or None
    try:
        value: Any = json.loads(body)
    except ValueError:
        return None
    for key in str(route.get("path") or "").split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value) or None


def _vendor_headers(headers: Mapping[str, str], signature: str) -> dict[str, str]:
    """The vendor's own ``x-`` headers, without the signature and the proxy's."""
    return {
        name: value
        for name, value in headers.items()
        if name.startswith("x-")
        and not name.startswith("x-forwarded-")
        and name not in {"x-real-ip", signature.lower()}
    }


async def _webhooks(registration: RegistrationSnapshot) -> Optional[dict[str, Any]]:
    """The ``webhooks`` block of the listing's current definition, which
    checks and routes a delivery before any install is known."""
    async with db_session.SystemSessionLocal() as session:
        definitions = await listing_definitions(session, [registration.listing_uid])
    webhooks = definitions.get(registration.listing_uid or "", {}).get("webhooks")
    return webhooks if isinstance(webhooks, dict) else None


def _route_spec(route: Any) -> Optional[tuple[str, str]]:
    """Where a ``webhooks.route`` reads its value: a header, or a body path."""
    if not isinstance(route, Mapping):
        return None
    if isinstance(route.get("header"), str):
        return ("header", route["header"].lower())
    if isinstance(route.get("path"), str):
        return ("path", route["path"])
    return None


async def _route_specs(listing_uid: str) -> set[tuple[str, str]]:
    """Every place a version of the listing reads its route value from: an
    install is pinned to one of them."""
    route = col(MarketplaceListingVersion.definition)["webhooks"]["route"]
    async with db_session.SystemSessionLocal() as session:
        rows = (
            await session.exec(
                select(route)
                .join(
                    MarketplaceListing,
                    col(MarketplaceListing.id) == MarketplaceListingVersion.listing_id,
                )
                .where(MarketplaceListing.uid == listing_uid)
                .distinct()
            )
        ).all()
    return {spec for row in rows if (spec := _route_spec(row)) is not None}


async def _routed(
    listing_uid: str,
    specs: set[tuple[str, str]],
    headers: Mapping[str, str],
    body: bytes,
) -> list[plugin_installs.IndexedInstall]:
    """The installs a delivery's route values name, one index lookup for each
    value the listing's versions read from it."""
    values = {
        value
        for kind, where in specs
        if (value := _route_value({kind: where}, headers, body)) is not None
    }
    found: dict[tuple[int, int], plugin_installs.IndexedInstall] = {}
    for value in sorted(values):
        for install in await plugin_installs.routed(listing_uid, value):
            found.setdefault((install.guild_id, install.install_id), install)
    return [found[key] for key in sorted(found)]


async def _pending(
    install: plugin_installs.IndexedInstall,
    registration: RegistrationSnapshot,
    delivery_id: str,
    *,
    headers: Mapping[str, str],
    body: bytes,
) -> Optional[GuildPlugin]:
    """The install a delivery is still owed to, as it is pinned, or ``None``
    when there is no install of this plug-in to take it, its pinned route does not
    read the value it is indexed by from this delivery, or it already has it."""
    async with cohorts.system_session(install.guild_id) as session:
        await set_rls_context(session, SystemGuild(install.guild_id, read_only=True))
        plugin = (
            await session.exec(
                select(GuildPlugin).where(GuildPlugin.id == install.install_id)
            )
        ).first()
        if (
            plugin is None
            or not plugin.enabled
            or not owns_install(plugin, registration)
        ):
            return None
        route = ((plugin.definition or {}).get("webhooks") or {}).get("route")
        indexed = plugin_installs.hook_route(plugin)
        if indexed is None or _route_value(route, headers, body) != indexed:
            return None
        seen = (
            await session.exec(
                select(PluginHookDelivery.delivery_id).where(
                    PluginHookDelivery.install_id == install.install_id,
                    PluginHookDelivery.delivery_id == delivery_id,
                    PluginHookDelivery.expires_at > datetime.now(timezone.utc),
                )
            )
        ).first()
    return None if seen is not None else plugin


def _remember(install_id: int, delivery_id: str) -> Any:
    """The statement recording a delivery an install accepted, for 24 hours:
    its id, unless one still remembered holds it."""
    expires_at = datetime.now(timezone.utc) + DELIVERY_TTL
    statement = pg_insert(PluginHookDelivery).values(
        install_id=install_id, delivery_id=delivery_id, expires_at=expires_at
    )
    return statement.on_conflict_do_update(
        index_elements=[PluginHookDelivery.install_id, PluginHookDelivery.delivery_id],
        set_={"expires_at": expires_at},
        where=col(PluginHookDelivery.expires_at) <= datetime.now(timezone.utc),
    ).returning(PluginHookDelivery.delivery_id)


async def _record(install: plugin_installs.IndexedInstall, delivery_id: str) -> None:
    async with cohorts.system_session(install.guild_id) as session:
        await set_rls_context(session, SystemGuild(install.guild_id))
        await session.exec(_remember(install.install_id, delivery_id))
        await session.commit()


async def _forward(
    install: plugin_installs.IndexedInstall,
    registration: RegistrationSnapshot,
    plugin: GuildPlugin,
    webhooks: Mapping[str, Any],
    *,
    delivery_id: str,
    headers: Mapping[str, str],
    body: bytes,
) -> int:
    """A container's install: the delivery goes to its ``webhook`` hook, as
    its pinned ``webhooks`` describe it."""
    try:
        await flows.call_hook(
            "webhook",
            public_id=registration.public_id,
            base_url=registration.base_url,
            guild_id=install.guild_id,
            install_id=install.install_id,
            body={
                "connection": webhooks["route"]["connection"],
                "headers": _vendor_headers(headers, str(webhooks["verify"]["header"])),
                "body": body.decode("utf-8", errors="replace"),
            },
        )
    except flows.HookError as exc:
        logger.warning(
            "plug-in hooks: %s did not accept a delivery for guild %s (%s)",
            registration.public_id,
            install.guild_id,
            exc,
        )
        return 502
    await _record(install, delivery_id)
    return 202


async def _map(
    install: plugin_installs.IndexedInstall,
    registration: RegistrationSnapshot,
    plugin: GuildPlugin,
    webhooks: Mapping[str, Any],
    *,
    delivery_id: str,
    headers: Mapping[str, str],
    body: bytes,
) -> int:
    """A declarative plug-in's install: its pinned ``webhooks`` map the delivery
    to an event, emitted as a container's is, and to a connection's state.
    The delivery is recorded with them, so a redelivery emits nothing.

    A mapping that may answer if asked again records nothing and answers 503,
    so the vendor sends it again; one that cannot is recorded beside whatever
    did map."""
    try:
        payload: Any = json.loads(body)
    except ValueError:
        payload = None
    route = webhooks["route"]
    try:
        delivered = await declarative.map_delivery(
            plugin.definition,
            headers=_vendor_headers(headers, str(webhooks["verify"]["header"])),
            payload=payload,
            connection=without_tokens((plugin.config or {}).get(route["connection"])),
        )
    except ExpressionError as exc:
        logger.warning(
            "plug-in hooks: %s will map delivery %s for guild %s when it comes again (%s)",
            registration.public_id,
            delivery_id,
            install.guild_id,
            exc,
        )
        return 503
    for failure in delivered.failures:
        logger.warning(
            "plug-in hooks: %s could not map delivery %s for guild %s (%s)",
            registration.public_id,
            delivery_id,
            install.guild_id,
            failure,
        )
    async with cohorts.system_session(install.guild_id) as session:
        await set_rls_context(session, SystemGuild(install.guild_id))
        claimed = (
            await session.exec(_remember(install.install_id, delivery_id))
        ).first()
        if claimed is None:
            return 202
        if delivered.event is not None:
            event_type, event = delivered.event
            try:
                await keep_event(
                    session,
                    plugin,
                    registration,
                    event_type=event_type,
                    payload=event,
                    initiative_id=None,
                )
            except PluginChannelError as exc:
                logger.warning(
                    "plug-in hooks: %s emitted %s from delivery %s for guild %s, "
                    "which was refused (%s)",
                    registration.public_id,
                    event_type,
                    delivery_id,
                    install.guild_id,
                    exc.code,
                )
        if delivered.status is not None:
            locked = await guild_plugins_service.lock_install(session, plugin.id)
            if locked is not None and set_connection_state(locked, *delivered.status):
                session.add(locked)
        await session.commit()
    return 202


async def receive(public_id: str, headers: Mapping[str, str], body: bytes) -> int:
    """Take one vendor delivery for ``public_id`` and answer its status.

    ``headers`` are the request's, with lowercased names.
    """
    registration = (await registration_lookup.load_registrations()).get(public_id)
    if registration is None or not registration.live or not registration.listing_uid:
        return 404
    webhooks = await _webhooks(registration)
    if webhooks is None:
        return 404
    verify = webhooks["verify"]
    key = str(verify["secret"])[len("{vendor.") : -1]
    secret = (await load_vendor_values(public_id)).get(key)
    if not secret or not _verified(verify, secret, headers, body):
        metrics.plugin_hook_deliveries.labels(outcome="refused").inc()
        return 401

    specs = await _route_specs(registration.listing_uid)
    current = _route_spec(webhooks["route"])
    if current is not None:
        specs.add(current)
    installs = [
        install
        for install in await _routed(registration.listing_uid, specs, headers, body)
        if registration.serves(install.guild_id)
    ]
    if not installs:
        metrics.plugin_hook_deliveries.labels(outcome="unroutable").inc()
        return 202

    delivery_id = headers.get(str(webhooks["dedup"]).lower(), "")
    if not delivery_id or len(delivery_id) > DELIVERY_ID_MAX_LENGTH:
        return 400
    limit = asyncio.Semaphore(FORWARD_CONCURRENCY)

    async def bounded(install: plugin_installs.IndexedInstall) -> int:
        async with limit:
            plugin = await _pending(
                install, registration, delivery_id, headers=headers, body=body
            )
            if plugin is None:
                return 202
            pinned = (plugin.definition or {}).get("webhooks")
            if not isinstance(pinned, dict):
                return 202
            # A declarative registration has no hook to forward to, whatever
            # version an install is still pinned to.
            declared = registration.declarative or is_declarative(plugin.definition)
            hand = _map if declared else _forward
            return await hand(
                install,
                registration,
                plugin,
                pinned,
                delivery_id=delivery_id,
                headers=headers,
                body=body,
            )

    # The worst answer stands: 503 when one install will map it once it comes
    # again, 502 when one did not accept it.
    status = max(await asyncio.gather(*(bounded(install) for install in installs)))
    outcome = "delivered" if status == 202 else "failed"
    metrics.plugin_hook_deliveries.labels(outcome=outcome).inc()
    return status
