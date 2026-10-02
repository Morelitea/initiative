"""A vendor's webhooks, received for the app that declares them.

An app whose manifest declares ``webhooks`` has one address on this
deployment, ``POST /api/v1/app-hooks/{public_id}``, which the operator gives
the vendor. :func:`receive` takes each delivery through four steps:

1. The signature is checked with the registration's vendor secret. A delivery
   that does not verify is refused (401).
2. The route value is read from the JSON body, at the path the manifest's
   ``webhooks.route`` names, or from the header it names, and matched against
   the install index (:func:`app_installs.routed`). A delivery nothing
   matches is answered 202 and nothing is stored.
3. For each matched install, in its own community and several communities at
   once, read as the version that install is pinned to: a delivery id the
   install has already accepted (``app_hook_deliveries``) is skipped.
   Otherwise a container's install has the raw body and the vendor's ``x-``
   headers sent to its ``webhook`` hook with a ``lifecycle`` token naming that
   install, and a 2xx records the id for 24 hours. A declarative app's install
   maps it with its ``events`` and ``status``: the event goes to the outbox as
   a container's emission does, the state to the install's configuration
   state, and the id is recorded with them.
4. 202 when every matched install accepted it or already had; otherwise 502,
   so the vendor's redelivery reaches only the ones that did not.

The index row that routes a delivery is written only when a community's
connect stored the routed value, which the app's ``after_connect`` hook
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
from app.models.tenant.app_hook_delivery import DELIVERY_ID_MAX_LENGTH, AppHookDelivery
from app.models.tenant.guild_app import GuildApp
from app.services.marketplace import app_installs, declarative, registration_lookup
from app.services.marketplace.expressions import ExpressionError
from app.services.marketplace.registration_lookup import (
    RegistrationSnapshot,
    is_declarative,
)
from app.services.marketplace.vendor_values import (
    listing_definitions,
    load_vendor_values,
)
from app.services.tenant import app_connection_flows as flows
from app.services.tenant import guild_apps as guild_apps_service
from app.services.tenant.app_channels import (
    AppChannelError,
    keep_event,
    owns_install,
    set_connection_state,
)
from app.services.tenant.app_config import without_tokens
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


def _route_value(body: bytes, path: str) -> Optional[str]:
    """The value at ``path`` (keys joined by ``.``) in a JSON body, as the
    install index stores it, or ``None``."""
    try:
        value: Any = json.loads(body)
    except ValueError:
        return None
    for key in path.split("."):
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


async def _pending(
    install: app_installs.IndexedInstall,
    registration: RegistrationSnapshot,
    delivery_id: str,
) -> Optional[GuildApp]:
    """The install a delivery is still owed to, as it is pinned, or ``None``
    when there is no install of this app to take it or it already has."""
    async with cohorts.system_session(install.guild_id) as session:
        await set_rls_context(session, SystemGuild(install.guild_id, read_only=True))
        app = (
            await session.exec(
                select(GuildApp).where(GuildApp.id == install.install_id)
            )
        ).first()
        if app is None or not app.enabled or not owns_install(app, registration):
            return None
        seen = (
            await session.exec(
                select(AppHookDelivery.delivery_id).where(
                    AppHookDelivery.install_id == install.install_id,
                    AppHookDelivery.delivery_id == delivery_id,
                    AppHookDelivery.expires_at > datetime.now(timezone.utc),
                )
            )
        ).first()
    return None if seen is not None else app


def _remember(install_id: int, delivery_id: str) -> Any:
    """The statement recording a delivery an install accepted, for 24 hours:
    its id, unless one still remembered holds it."""
    expires_at = datetime.now(timezone.utc) + DELIVERY_TTL
    statement = pg_insert(AppHookDelivery).values(
        install_id=install_id, delivery_id=delivery_id, expires_at=expires_at
    )
    return statement.on_conflict_do_update(
        index_elements=[AppHookDelivery.install_id, AppHookDelivery.delivery_id],
        set_={"expires_at": expires_at},
        where=col(AppHookDelivery.expires_at) <= datetime.now(timezone.utc),
    ).returning(AppHookDelivery.delivery_id)


async def _record(install: app_installs.IndexedInstall, delivery_id: str) -> None:
    async with cohorts.system_session(install.guild_id) as session:
        await set_rls_context(session, SystemGuild(install.guild_id))
        await session.exec(_remember(install.install_id, delivery_id))
        await session.commit()


async def _forward(
    install: app_installs.IndexedInstall,
    registration: RegistrationSnapshot,
    app: GuildApp,
    webhooks: Mapping[str, Any],
    *,
    delivery_id: str,
    headers: Mapping[str, str],
    body: bytes,
) -> bool:
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
            "app hooks: %s did not accept a delivery for guild %s (%s)",
            registration.public_id,
            install.guild_id,
            exc,
        )
        return False
    await _record(install, delivery_id)
    return True


async def _map(
    install: app_installs.IndexedInstall,
    registration: RegistrationSnapshot,
    app: GuildApp,
    webhooks: Mapping[str, Any],
    *,
    delivery_id: str,
    headers: Mapping[str, str],
    body: bytes,
) -> bool:
    """A declarative app's install: its pinned ``webhooks`` map the delivery
    to an event, emitted as a container's is, and to a connection's state.
    The delivery is recorded with them, so a redelivery emits nothing."""
    try:
        payload: Any = json.loads(body)
    except ValueError:
        payload = None
    route = webhooks["route"]
    try:
        delivered = await declarative.map_delivery(
            app.definition,
            headers=_vendor_headers(headers, str(webhooks["verify"]["header"])),
            payload=payload,
            connection=without_tokens((app.config or {}).get(route["connection"])),
        )
    except ExpressionError as exc:
        logger.warning(
            "app hooks: %s could not map a delivery for guild %s (%s)",
            registration.public_id,
            install.guild_id,
            exc,
        )
        delivered = declarative.Delivered()
    async with cohorts.system_session(install.guild_id) as session:
        await set_rls_context(session, SystemGuild(install.guild_id))
        claimed = (
            await session.exec(_remember(install.install_id, delivery_id))
        ).first()
        if claimed is None:
            return True
        if delivered.event is not None:
            event_type, event = delivered.event
            try:
                await keep_event(
                    session,
                    app,
                    registration,
                    event_type=event_type,
                    payload=event,
                    initiative_id=None,
                )
            except AppChannelError as exc:
                logger.warning(
                    "app hooks: %s emitted %s for guild %s, which was refused (%s)",
                    registration.public_id,
                    event_type,
                    install.guild_id,
                    exc.code,
                )
        if delivered.status is not None:
            locked = await guild_apps_service.lock_install(session, app.id)
            if locked is not None and set_connection_state(locked, *delivered.status):
                session.add(locked)
        await session.commit()
    return True


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
        metrics.app_hook_deliveries.labels(outcome="refused").inc()
        return 401

    route = webhooks["route"]
    value = (
        headers.get(str(route["header"]).lower()) or None
        if "header" in route
        else _route_value(body, route["path"])
    )
    installs = (
        []
        if value is None
        else await app_installs.routed(registration.listing_uid, value)
    )
    if not installs:
        metrics.app_hook_deliveries.labels(outcome="unroutable").inc()
        return 202

    delivery_id = headers.get(str(webhooks["dedup"]).lower(), "")
    if not delivery_id or len(delivery_id) > DELIVERY_ID_MAX_LENGTH:
        return 400
    limit = asyncio.Semaphore(FORWARD_CONCURRENCY)

    async def bounded(install: app_installs.IndexedInstall) -> bool:
        async with limit:
            app = await _pending(install, registration, delivery_id)
            if app is None:
                return True
            pinned = (app.definition or {}).get("webhooks")
            if not isinstance(pinned, dict):
                return True
            # A declarative registration has no hook to forward to, whatever
            # version an install is still pinned to.
            declared = registration.declarative or is_declarative(app.definition)
            hand = _map if declared else _forward
            return await hand(
                install,
                registration,
                app,
                pinned,
                delivery_id=delivery_id,
                headers=headers,
                body=body,
            )

    held = await asyncio.gather(*(bounded(install) for install in installs))
    outcome = "delivered" if all(held) else "failed"
    metrics.app_hook_deliveries.labels(outcome=outcome).inc()
    return 202 if all(held) else 502
