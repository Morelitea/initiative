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

import logging
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional

from jwt import PyJWK
from sqlalchemy import true as sa_true
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from app.db import session as db_session
from app.models.platform.app_service_registration import (
    AppServiceRegistration,
    browser_base,
    is_live,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CACHE_TTL_SECONDS",
    "DelegationKey",
    "InstallState",
    "RegistrationSnapshot",
    "any_delegate_registered",
    "delegate_jwks",
    "delegation_allowed",
    "resolve_delegated_member",
    "delegation_keys_for",
    "frame_origins",
    "install_state",
    "invalidate_registrations",
    "live_delegate",
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
    #: Where Initiative's own server calls this app.
    base_url: str
    #: Where a person's browser loads its surfaces, when the app answers there
    #: rather than at ``base_url``. Read through :attr:`browser_base`.
    embed_origin: Optional[str]
    #: Origins this app's surfaces may be framed from and postMessage'd to.
    allowed_origins: tuple[str, ...]
    #: Operator-conferred powers, for callers that gate on one.
    grants: tuple[str, ...]
    #: Public verification keys this app signs delegation tokens with, by the
    #: ``kid`` a token names. Parsed once when the snapshot is built rather than
    #: per token. Empty on an app that has not been provisioned with one.
    delegation_keys: Mapping[str, Any]
    #: The same keys as provisioned — public JWK entries, for the published
    #: delegate key set (:func:`delegate_jwks`). Public halves only: the write
    #: path refuses anything else (``normalize_delegation_jwks``).
    delegation_jwk_entries: tuple[Mapping[str, Any], ...]
    #: The deployment installs this app in every guild (§7.7).
    mandatory: bool
    #: The operator's kill switch. False stops every channel this app has.
    enabled: bool
    status: str

    @property
    def live(self) -> bool:
        """Whether anything may flow through this app right now.

        Defers to :func:`is_live` so the embed plane and the data plane answer
        this from the same rule rather than each stating one.
        """
        return is_live(self)

    @property
    def browser_base(self) -> str:
        """The base to build an address a browser will be sent to."""
        return browser_base(self)


def _parse_delegation_keys(row: AppServiceRegistration) -> Mapping[str, Any]:
    """Build the ``kid`` → key index for one registration.

    The keys were validated when they were stored, so anything unusable here
    is a surprise worth logging rather than a case to model: the entry is left
    out, and a token naming it finds no key.
    """
    key_set = row.delegation_jwks or {}
    parsed: dict[str, Any] = {}
    for entry in key_set.get("keys", []) or []:
        kid = entry.get("kid") if isinstance(entry, dict) else None
        if not kid:
            continue
        try:
            parsed[kid] = PyJWK.from_dict(entry).key
        except Exception:
            logger.warning(
                "app services: %s has an unusable delegation key %r", row.public_id, kid
            )
    return MappingProxyType(parsed)


def _public_jwk_entries(row: AppServiceRegistration) -> tuple[Mapping[str, Any], ...]:
    """The stored key set's entries, as read-only mappings for the snapshot."""
    key_set = row.delegation_jwks or {}
    return tuple(
        MappingProxyType(dict(entry))
        for entry in key_set.get("keys", []) or []
        if isinstance(entry, dict)
    )


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
            embed_origin=row.embed_origin,
            allowed_origins=tuple(row.allowed_origins or []),
            grants=tuple(row.grants or []),
            delegation_keys=_parse_delegation_keys(row),
            delegation_jwk_entries=_public_jwk_entries(row),
            mandatory=bool(row.mandatory),
            enabled=bool(row.enabled),
            status=row.status,
        )
        for row in rows
    }
    _cache = snapshots
    _loaded_at = time.monotonic()
    return snapshots


async def frame_origins() -> tuple[str, ...]:
    """Every origin an app surface may be framed from, deduped and ordered.

    This deployment's registrations are its trusted-site list. An origin gets
    on it by an operator wiring up an app service and that service's handshake
    confirming the manifest it serves — so what comes back describes the
    services this deployment runs, and says nothing about any guild or reader.

    Only live registrations count, which is how the operator's kill switch and
    a failed re-verification reach the frame policy: within the cache TTL, a
    stopped or drifted app's origins are gone from it.
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
    #: Whether this app is one that acts as members, and so has something for
    #: each of them to authorize. An operator clearing the grant takes the
    #: question away everywhere the app is installed.
    delegates: bool = False


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
        delegates="delegation" in snapshot.grants,
    )


async def mandatory_registrations() -> list[RegistrationSnapshot]:
    """The apps this deployment installs into every guild.

    Only the enabled ones: a registration the operator switched off installs
    nowhere new, because the kill switch outranks the flag (§7.7).

    Deliberately ``enabled`` rather than :attr:`RegistrationSnapshot.live`. An
    install is a local row, and a mandatory app whose container has not booted
    yet is the ordinary case on a fresh deployment — it discovers the guild on
    its next ``/installs`` pull. Waiting for a handshake here would make guild
    creation depend on a container being up. What the unverified state does stop
    is everything that flows *through* the app, which is what ``live`` gates.
    """
    return [
        snapshot
        for snapshot in (await load_registrations()).values()
        if snapshot.mandatory and snapshot.enabled
    ]


@dataclass(frozen=True)
class DelegationKey:
    """A verification key, and the app whose registration published it."""

    registration: RegistrationSnapshot
    key: Any


async def delegation_keys_for(kid: str) -> tuple[DelegationKey, ...]:
    """Every key a delegation token's ``kid`` could name.

    Only from registrations that are ``enabled`` and hold the ``delegation``
    grant, so an operator ends an app's ability to act with an edit rather than
    a key rotation.

    All matches rather than the first: a ``kid`` is an opaque label its owner
    chooses, so two apps may pick the same one, and the token belongs to
    whichever key verifies it. Resolution is by ``kid`` rather than by reading
    an app's name out of it, for the same reason.

    Deliberately ``enabled`` rather than :attr:`RegistrationSnapshot.live` — a
    delegate calls the API directly, so its ability to act follows the
    operator's kill switch, not whether its manifest was reachable at the last
    handshake.
    """
    if not kid:
        return ()
    return tuple(
        DelegationKey(registration=snapshot, key=key)
        for snapshot in (await load_registrations()).values()
        if snapshot.enabled and "delegation" in snapshot.grants
        for key in (snapshot.delegation_keys.get(kid),)
        if key is not None
    )


async def live_delegate(public_id: str) -> Optional[RegistrationSnapshot]:
    """The registration behind a named delegate, when it may act right now.

    One rule, stated once: the registration must be ``enabled`` and hold the
    ``delegation`` grant. Both the published key set and any lookup made on a
    delegate's say-so read it here, so an operator's edit reaches every one of
    them together within the cache TTL rather than some of them.

    Deliberately ``enabled`` rather than :attr:`RegistrationSnapshot.live`, for
    the reason :func:`delegation_keys_for` gives: a delegate calls the API
    directly, so what it may do follows the operator's kill switch rather than
    whether its manifest was reachable at the last handshake.
    """
    snapshot = (await load_registrations()).get(public_id)
    if snapshot is None or not snapshot.enabled or "delegation" not in snapshot.grants:
        return None
    return snapshot


async def delegate_jwks(public_id: str) -> dict[str, Any] | None:
    """One delegate's public verification keys, as a JWKS document.

    Per delegate, never merged. A ``kid`` is an opaque label its owner
    chooses, unique only within the registration that published it — which is
    why :func:`delegation_keys_for` resolves a token by trying every candidate
    and letting the signature decide. A document merging two registrations
    would hand a consumer two entries under one ``kid``, and a consumer that
    selects one key per ``kid`` (which is what a JWKS is for) would then reject
    calls signed with the other. One issuer, one key set.

    Served under the same rule that resolves a token: the registration must be
    ``enabled`` and hold the ``delegation`` grant, so an operator's edit
    reaches this and verification alike within the cache TTL. ``None`` when no
    such delegate is published here — the caller answers that as not found.
    """
    snapshot = await live_delegate(public_id)
    if snapshot is None:
        return None
    return {"keys": [dict(entry) for entry in snapshot.delegation_jwk_entries]}


async def any_delegate_registered() -> bool:
    """Whether some app on this deployment may delegate and can be verified.

    What every surface that is delegate-owned reads: the subscription
    endpoints refuse without one and the outbound dispatcher stays inert.
    """
    return any(
        snapshot.enabled
        and "delegation" in snapshot.grants
        and snapshot.delegation_keys
        for snapshot in (await load_registrations()).values()
    )


async def resolve_delegated_member(
    guild_id: int, public_id: str, subject: str
) -> int | None:
    """Which member a delegation token's subject names, or None.

    A subject is pairwise — derived per install — so resolving one needs both
    the guild it was minted in and the app it was minted for. Scoping to the
    signer is the part that matters: without it, an app could present a subject
    another app was given and act as that person.

    Read on the system engine and routed into the guild, because the subject
    table is guild content and the caller at this point is nobody yet.
    """
    if not public_id or not subject:
        return None

    from app.models.tenant.guild_app import GuildApp
    from app.services.marketplace.app_subjects import resolve_subject

    async with db_session.AdminSessionLocal() as session:
        try:
            await db_session.set_rls_context(
                session, guild_id=guild_id, guild_role="admin"
            )
            row = await resolve_subject(session, subject=subject)
            if row is None:
                return None
            # The subject resolved — now check it was minted for *this* app's
            # install, in this guild.
            install = (
                await session.exec(
                    select(GuildApp.id).where(
                        GuildApp.id == row.app_id,
                        GuildApp.enabled.is_(True),
                        GuildApp.definition["app_kind"].astext == "service",
                        GuildApp.definition["service"]["public_id"].astext == public_id,
                    )
                )
            ).first()
            if install is None:
                return None
            return row.user_id
        except SQLAlchemyError:
            logger.warning(
                "app services: subject lookup could not read guild %s", guild_id
            )
            return None


async def delegation_allowed(
    guild_id: int, public_id: str, user_id: int, *, need_write: bool
) -> bool:
    """Whether this app may act as this member, here, right now.

    Two separate parties have to have said yes, and this asks both in one read
    of the guild's own schema:

    * **The guild installed the app.** The install is what makes an app present
      in a guild, so it is also what bounds a delegate to the guilds that chose
      it — uninstalling ends that reach, which is the property §10.3 of the
      platform design claims.
    * **The member authorized it to act as them**, to at least the depth this
      call needs. Installing is the guild's decision; carrying one person's name
      is that person's.

    The install is matched on the pinned definition's service id, the same
    identity :func:`registration_for_definition` resolves an install by. A row's
    ``listing_uid`` is re-recorded from the manifest on every handshake, so it
    names the listing an app currently claims rather than the app itself.

    Read per call rather than cached: the registration snapshot can afford a
    TTL because an operator's kill switch is deployment-wide and rare, while an
    uninstall and a withdrawal are each a decision made here and expected to
    bite at once.
    """
    if not public_id:
        return False

    from app.models.tenant.guild_app import GuildApp
    from app.models.tenant.guild_app_user_delegation import GuildAppUserDelegation

    write_leg = GuildAppUserDelegation.can_write.is_(True) if need_write else sa_true()

    async with db_session.AdminSessionLocal() as session:
        try:
            # Guild content lives in the guild's own schema, so the read is
            # routed there. `admin` because this asks what the guild has and
            # what one member said, not what any particular caller may see.
            await db_session.set_rls_context(
                session, guild_id=guild_id, guild_role="admin"
            )
            found = (
                await session.exec(
                    select(GuildApp.id)
                    .join(
                        GuildAppUserDelegation,
                        GuildAppUserDelegation.app_id == GuildApp.id,
                    )
                    .where(
                        GuildApp.enabled.is_(True),
                        GuildApp.definition["app_kind"].astext == "service",
                        GuildApp.definition["service"]["public_id"].astext == public_id,
                        GuildAppUserDelegation.user_id == user_id,
                        GuildAppUserDelegation.revoked_at.is_(None),
                        GuildAppUserDelegation.can_read.is_(True),
                        write_leg,
                    )
                )
            ).first()
        except SQLAlchemyError:
            # A guild id naming no guild has no schema to route into, and
            # nothing is installed in a guild that is not there.
            logger.warning(
                "app services: delegation check could not read guild %s", guild_id
            )
            return False
    return found is not None
