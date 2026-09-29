"""What the request path knows about the app services this deployment wired up.

``app_service_registrations`` is deployment configuration: no guild role and no
bare login role holds a grant on it, and an installed app's standing reads only
the few columns of its own row. Everything else a request needs from a
registration — is this app wired up, is it live, where does it live, which
origins may frame it, and which keys it signs with — is loaded once on the
system engine and kept as an immutable snapshot the request path reads.

**Freshness is bounded, and a write is immediate.** An operator's kill switch
has to bite quickly, so the cache is short-lived *and* dropped in-process on
any registration or publisher write. A replica that did not serve the write
picks the change up within the TTL.

Whether a registration is live is computed by the database with the one rule
in :func:`~app.models.platform.app_service_registration.registration_live_sql`,
the same one the install standing asks, and carried on the snapshot.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional

from jwt import PyJWK
from sqlalchemy import literal_column
from sqlmodel import select

from app.db import session as db_session
from app.models.platform.app_service_registration import (
    AppServiceRegistration,
    browser_base,
    registration_live_sql,
)
from app.models.platform.publisher import Publisher

logger = logging.getLogger(__name__)

__all__ = [
    "CACHE_TTL_SECONDS",
    "InstallState",
    "RegistrationSnapshot",
    "app_is_offered",
    "enabled_service_ids",
    "frame_origins",
    "install_state",
    "invalidate_registrations",
    "live_registration_clause",
    "load_registrations",
    "mandatory_registrations",
    "registration_for_definition",
    "service_public_id",
]

#: How long a loaded snapshot is reused. Short enough that deactivating a
#: registration takes effect promptly on every replica, long enough that a busy
#: guild's app reads do not each open a system-engine connection.
CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class RegistrationSnapshot:
    """One registration, as everything outside the operator surface sees it."""

    public_id: str
    listing_uid: Optional[str]
    #: Where Initiative's own server calls this app. Empty for a registry
    #: container the operator has not placed yet, which is never live.
    base_url: str
    #: Where a person's browser loads its surfaces, when the app answers there
    #: rather than at ``base_url``. Read through :attr:`browser_base`.
    embed_origin: Optional[str]
    #: Origins this app's surfaces may be framed from and postMessage'd to.
    allowed_origins: tuple[str, ...]
    #: Public verification keys this app signs with — its client assertions at
    #: the token endpoint — by the ``kid`` a JWT names. Parsed once when the
    #: snapshot is built rather than per token.
    #: Empty on an app that has not been provisioned with a pasted set.
    keys: Mapping[str, Any]
    #: The deployment installs this app in every guild (§7.7).
    mandatory: bool
    #: The operator's kill switch on the registration itself.
    enabled: bool
    #: Whether anything may flow through this app right now: enabled, its
    #: publisher enabled, a location, and a key set to verify against.
    #: Computed by the database from ``registration_live_sql`` when the
    #: snapshot is loaded.
    live: bool
    #: The most any install of this app may be granted, as the operator set it.
    #: Not secret: it bounds what a community's seat may grant.
    scope_ceiling: tuple[str, ...] = ()
    #: Where the app publishes its key set, when it does
    #: (:mod:`app.services.marketplace.app_keys`).
    jwks_uri: Optional[str] = None

    @property
    def browser_base(self) -> str:
        """The base to build an address a browser will be sent to."""
        return browser_base(self)


def _parse_keys(row: AppServiceRegistration) -> Mapping[str, Any]:
    """Build the ``kid`` → key index for one registration.

    The keys were validated when they were stored, so anything unusable here
    is a surprise worth logging rather than a case to model: the entry is left
    out, and a token naming it finds no key.
    """
    key_set = row.jwks or {}
    parsed: dict[str, Any] = {}
    for entry in key_set.get("keys", []) or []:
        kid = entry.get("kid") if isinstance(entry, dict) else None
        if not kid:
            continue
        try:
            parsed[kid] = PyJWK.from_dict(entry).key
        except Exception:
            logger.warning(
                "app services: %s has an unusable key %r", row.public_id, kid
            )
    return MappingProxyType(parsed)


_cache: dict[str, RegistrationSnapshot] | None = None
_loaded_at: float = 0.0


def invalidate_registrations() -> None:
    """Drop the snapshot. Called on every registration write."""
    global _cache, _loaded_at
    _cache = None
    _loaded_at = 0.0


def live_registration_clause() -> Any:
    """:func:`registration_live_sql` over ``app_service_registrations`` joined
    to ``publishers``, for a query that selects both by their table names."""
    return literal_column(
        registration_live_sql(
            AppServiceRegistration.__tablename__, Publisher.__tablename__
        )
    )


async def load_registrations(*, force: bool = False) -> dict[str, RegistrationSnapshot]:
    """Every registration, keyed by ``public_id``, with whether it is live.

    Runs on the system engine: the table carries no request-path grant beyond
    the install standing's few columns, so this is the reader everything else
    shares. One statement joins each registration to its publisher.
    """
    global _cache, _loaded_at
    if not force and _cache is not None:
        if (time.monotonic() - _loaded_at) < CACHE_TTL_SECONDS:
            return _cache

    async with db_session.SystemSessionLocal() as session:
        rows = (
            await session.exec(
                select(
                    AppServiceRegistration,
                    live_registration_clause().label("live"),
                )
                .join(Publisher, Publisher.id == AppServiceRegistration.publisher_id)
                .order_by(AppServiceRegistration.public_id)
            )
        ).all()

    snapshots = {
        row.public_id: RegistrationSnapshot(
            public_id=row.public_id,
            listing_uid=row.listing_uid,
            base_url=row.base_url or "",
            embed_origin=row.embed_origin,
            allowed_origins=tuple(row.allowed_origins or []),
            keys=_parse_keys(row),
            mandatory=bool(row.mandatory),
            enabled=bool(row.enabled),
            live=bool(live),
            scope_ceiling=tuple(sorted(row.scope_ceiling or [])),
            jwks_uri=row.jwks_uri,
        )
        for row, live in rows
    }
    _cache = snapshots
    _loaded_at = time.monotonic()
    return snapshots


async def frame_origins() -> tuple[str, ...]:
    """Every origin an app surface may be framed from, deduped and ordered.

    This deployment's registrations are its trusted-site list. An origin gets
    on it by an operator wiring up an app service — so what comes back
    describes the services this deployment runs, and says nothing about any
    guild or reader.

    Only live registrations count, which is how the operator's kill switch and
    a publisher's reach the frame policy: within the cache TTL, a stopped app's
    origins are gone from it.
    """
    snapshots = await load_registrations()
    return tuple(
        sorted(
            {
                origin
                for snapshot in snapshots.values()
                if snapshot.live
                for origin in snapshot.allowed_origins
            }
        )
    )


def service_public_id(definition: Mapping[str, Any] | None) -> Optional[str]:
    """The app service a pinned definition names, if it names one.

    Only a ``service`` app has one — a tool instance mounts one of this build's
    own tools and an embed opens a configured surface, and neither has a
    container behind it.
    """
    if not isinstance(definition, Mapping):
        return None
    if definition.get("app_kind") != "service":
        return None
    service = definition.get("service")
    if not isinstance(service, dict):
        return None
    public_id = service.get("public_id")
    return public_id if isinstance(public_id, str) and public_id else None


async def registration_for_definition(
    definition: dict[str, Any] | None,
) -> Optional[RegistrationSnapshot]:
    """The registration behind an installed app, or ``None``.

    ``None`` covers both "this app has no service" and "this deployment has not
    wired that service up" — callers that need the difference read
    :func:`service_public_id` first.
    """
    public_id = service_public_id(definition)
    if public_id is None:
        return None
    return (await load_registrations()).get(public_id)


@dataclass(frozen=True)
class InstallState:
    """What an installed app's registration says about it, for a client.

    Both halves are derived rather than stored, which is what makes an
    operator's edits take effect without touching a single install: clearing
    ``mandatory`` turns every copy into an ordinary app, and the kill switch
    makes every copy unavailable, in the time it takes a cached snapshot to
    expire.
    """

    mandatory: bool = False
    available: bool = True
    #: The most the operator allows any install of this app to be granted.
    scope_ceiling: tuple[str, ...] = ()


async def install_state(definition: dict[str, Any] | None) -> InstallState:
    """The registration-derived state of one install.

    An app with no service behind it — a tool instance, an embed — is always
    available and never mandatory: there is no registration for it to depend on.
    """
    public_id = service_public_id(definition)
    if public_id is None:
        return InstallState()
    snapshot = (await load_registrations()).get(public_id)
    if snapshot is None:
        # Installed here, but this deployment has not wired the service up (or
        # no longer does). Nothing it offers can be reached.
        return InstallState(mandatory=False, available=False)
    return InstallState(
        mandatory=snapshot.mandatory,
        available=snapshot.live,
        scope_ceiling=snapshot.scope_ceiling,
    )


async def enabled_service_ids() -> frozenset[str]:
    """Every app service this deployment has wired up and switched on.

    What the catalog reads to decide which app listings it offers: an app is
    published to everyone, and registering it is how a deployment says it runs
    that one. A listing naming a service that is not in here is not offered,
    because installing it would produce an app with nothing behind it.

    Only live registrations: an app switched off, or whose publisher is, or
    that has no key set, is not offered.
    """
    return frozenset(
        snapshot.public_id
        for snapshot in (await load_registrations()).values()
        if snapshot.live
    )


async def app_is_offered(definition: dict[str, Any] | None) -> bool:
    """Whether this deployment offers the app a listing describes.

    The per-listing spelling of :func:`enabled_service_ids`, for the paths that
    hold one definition rather than a query: the listing page and the install.

    An app with no service behind it — one that mounts one of this build's own
    tools — is always offered, because there is no registration for it to
    depend on.
    """
    public_id = service_public_id(definition)
    if public_id is None:
        return True
    snapshot = (await load_registrations()).get(public_id)
    return snapshot is not None and snapshot.live


async def mandatory_registrations() -> list[RegistrationSnapshot]:
    """The apps this deployment installs into every guild.

    Only the live ones: a registration the operator switched off, or whose
    publisher is off, installs nowhere new, because the kill switch outranks
    the flag (§7.7). Whether the app's container is up is not asked: an
    install is a local row, and the app finds the guild on its next
    installations pull.
    """
    return [
        snapshot
        for snapshot in (await load_registrations()).values()
        if snapshot.mandatory and snapshot.live
    ]
