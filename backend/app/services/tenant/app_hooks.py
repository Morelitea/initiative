"""A vendor's webhooks, received for the app that declares them.

An app whose manifest declares ``webhooks`` has one address on this
deployment, ``POST /api/v1/app-hooks/{public_id}``, which the operator gives
the vendor. :func:`receive` takes each delivery through four steps:

1. The signature is checked with the registration's vendor secret. A delivery
   that does not verify is refused (401).
2. The route value is read from the JSON body, at the path the manifest's
   ``webhooks.route`` names, and matched against the install index
   (:func:`app_installs.routed`). A delivery nothing matches is answered 202
   and nothing is stored.
3. For each matched install, in its own community: a delivery id the install
   has already accepted (``app_hook_deliveries``) is skipped; otherwise the
   raw body and the vendor's ``x-`` headers go to the app's ``webhook`` hook
   with a ``lifecycle`` token naming that install, and a 2xx records the id
   for 24 hours.
4. 202 when every matched install accepted it or already had; otherwise 502,
   so the vendor's redelivery reaches only the ones that did not.

The index row that routes a delivery is written only when a community's
connect stored the routed value, which the app's ``after_connect`` hook
checked at the vendor.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from app.core import metrics
from app.db import session as db_session
from app.db.session import set_rls_context
from app.models.tenant.app_hook_delivery import DELIVERY_ID_MAX_LENGTH, AppHookDelivery
from app.models.tenant.guild_app import GuildApp
from app.services.marketplace import app_installs, registration_lookup
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.marketplace.vendor_values import (
    listing_definitions,
    load_vendor_values,
)
from app.services.tenant import app_connection_flows as flows
from app.services.tenant.app_channels import owns_install

logger = logging.getLogger(__name__)

__all__ = ["DELIVERY_TTL", "receive"]

#: How long an accepted delivery id is remembered.
DELIVERY_TTL = timedelta(hours=24)

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
    """The ``webhooks`` block of the listing's current definition."""
    async with db_session.SystemSessionLocal() as session:
        definitions = await listing_definitions(session, [registration.listing_uid])
    webhooks = definitions.get(registration.listing_uid or "", {}).get("webhooks")
    return webhooks if isinstance(webhooks, dict) else None


async def _already_accepted(
    install: app_installs.IndexedInstall,
    registration: RegistrationSnapshot,
    delivery_id: str,
) -> Optional[bool]:
    """Whether this install already accepted the delivery, or ``None`` when
    there is no install of this app to forward it to."""
    async with db_session.SystemSessionLocal() as session:
        await set_rls_context(session, guild_id=install.guild_id, read_only=True)
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
    return seen is not None


async def _record(install: app_installs.IndexedInstall, delivery_id: str) -> None:
    expires_at = datetime.now(timezone.utc) + DELIVERY_TTL
    async with db_session.SystemSessionLocal() as session:
        await set_rls_context(session, guild_id=install.guild_id)
        await session.exec(
            pg_insert(AppHookDelivery)
            .values(
                install_id=install.install_id,
                delivery_id=delivery_id,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                index_elements=[
                    AppHookDelivery.install_id,
                    AppHookDelivery.delivery_id,
                ],
                set_={"expires_at": expires_at},
            )
        )
        await session.commit()


async def _forward(
    install: app_installs.IndexedInstall,
    registration: RegistrationSnapshot,
    *,
    delivery_id: str,
    call: Mapping[str, Any],
) -> bool:
    """Step 3 for one community: whether it now holds the delivery."""
    accepted = await _already_accepted(install, registration, delivery_id)
    if accepted is not False:
        return True
    try:
        await flows.call_hook(
            "webhook",
            public_id=registration.public_id,
            base_url=registration.base_url,
            guild_id=install.guild_id,
            install_id=install.install_id,
            body=call,
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
    value = _route_value(body, route["path"])
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
    call = {
        "connection": route["connection"],
        "headers": _vendor_headers(headers, str(verify["header"])),
        "body": body.decode("utf-8", errors="replace"),
    }
    held = [
        await _forward(install, registration, delivery_id=delivery_id, call=call)
        for install in installs
    ]
    outcome = "delivered" if all(held) else "failed"
    metrics.app_hook_deliveries.labels(outcome=outcome).inc()
    return 202 if all(held) else 502
