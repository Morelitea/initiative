"""What the request path knows about the app services this deployment wired up.

``app_service_registrations`` is deliberately out of reach of a routed session:
it holds the shared secret, so no guild role and no bare login role holds a
grant on it. Everything a request legitimately needs from a registration is the
non-secret half — is this app wired up, is it turned on, where does it live, and
which origins may frame it — so that half is loaded once on the system engine
and kept as an immutable snapshot the request path reads.

Two properties matter, and they are the reason this is a snapshot rather than a
handle to a row:

* **Nothing secret leaves.** The snapshot has no secret field to serialize, so
  no caller downstream can reach one by accident.
* **Freshness is bounded, and a write is immediate.** An operator's kill switch
  has to bite quickly, so the cache is short-lived *and* dropped in-process on
  any registration write. A replica that did not serve the write picks the
  change up within the TTL.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from sqlmodel import select

from app.db import session as db_session
from app.models.platform.app_service_registration import AppServiceRegistration

__all__ = [
    "CACHE_TTL_SECONDS",
    "InstallState",
    "RegistrationSnapshot",
    "install_state",
    "invalidate_registrations",
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
    base_url: str
    #: Origins this app's surfaces may be framed from and postMessage'd to.
    allowed_origins: tuple[str, ...]
    #: Operator-conferred powers, for callers that gate on one.
    grants: tuple[str, ...]
    #: The deployment installs this app in every guild (§7.7).
    mandatory: bool
    #: The operator's kill switch. False stops every channel this app has.
    enabled: bool
    status: str

    @property
    def live(self) -> bool:
        """Whether anything may flow through this app right now."""
        return self.enabled


_cache: dict[str, RegistrationSnapshot] | None = None
_loaded_at: float = 0.0


def invalidate_registrations() -> None:
    """Drop the snapshot. Called on every registration write."""
    global _cache, _loaded_at
    _cache = None
    _loaded_at = 0.0


async def load_registrations(*, force: bool = False) -> dict[str, RegistrationSnapshot]:
    """Every registration, keyed by ``public_id``.

    Runs on the system engine: the table carries no request-path grant, so this
    is the one reader, and what it returns holds no secret material.
    """
    global _cache, _loaded_at
    if not force and _cache is not None:
        if (time.monotonic() - _loaded_at) < CACHE_TTL_SECONDS:
            return _cache

    async with db_session.AdminSessionLocal() as session:
        rows = (
            await session.exec(
                select(AppServiceRegistration).order_by(
                    AppServiceRegistration.public_id
                )
            )
        ).all()

    snapshots = {
        row.public_id: RegistrationSnapshot(
            public_id=row.public_id,
            listing_uid=row.listing_uid,
            base_url=row.base_url,
            allowed_origins=tuple(row.allowed_origins or []),
            grants=tuple(row.grants or []),
            mandatory=bool(row.mandatory),
            enabled=bool(row.enabled),
            status=row.status,
        )
        for row in rows
    }
    _cache = snapshots
    _loaded_at = time.monotonic()
    return snapshots


def service_public_id(definition: dict[str, Any] | None) -> Optional[str]:
    """The app service a pinned definition names, if it names one.

    Only a ``service`` app has one — a tool instance mounts one of this build's
    own tools and an embed opens a configured surface, and neither has a
    container behind it.
    """
    if not isinstance(definition, dict):
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
    return InstallState(mandatory=snapshot.mandatory, available=snapshot.enabled)


async def mandatory_registrations() -> list[RegistrationSnapshot]:
    """The apps this deployment installs into every guild.

    Only the enabled ones: a registration the operator switched off installs
    nowhere new, because the kill switch outranks the flag (§7.7).
    """
    return [
        snapshot
        for snapshot in (await load_registrations()).values()
        if snapshot.mandatory and snapshot.enabled
    ]
