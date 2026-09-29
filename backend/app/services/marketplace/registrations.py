"""Managing the deployment's app service registrations.

Three ways a registration arrives, and they meet in the same checks:

* **An operator adds one** through the ``apps.manage`` endpoints.
* **The deployment declares them** in ``APP_SERVICES_CONFIG``, a file a chart
  mounts, reconciled at boot. Reconciliation touches the database only, so a
  boot never waits on an app's container. An entry's ``vendor_env`` names the
  environment variables holding its vendor values, which are sealed into the
  registration on each boot.
* **The registry brings one** with a verified app listing
  (:mod:`app.services.marketplace.registry_entries`). Its row keeps what the
  registry says about the app; the operator edits only what is theirs on it
  (the switch, mandatory flag, origins, and a container's location and keys).
  An ``APP_SERVICES_CONFIG`` entry marked ``"registry": true`` gives those
  deployment facts and leaves the row the registry's; an entry without the
  mark takes the row over as the operator's.

Either way the registration states everything about itself: its
``public_id``, the ``listing_uid`` of the listing it speaks for, where it
lives, and its public keys (a pasted key set, a ``jwks_uri`` on its own
origin, or both). Nothing is fetched from the app to fill any of it in. Its
publisher is the row for its ``public_id`` prefix
(:mod:`app.services.marketplace.publishers`). The one secret it may hold is
its vendor values (:mod:`app.services.marketplace.vendor_values`), which the
operator sets on any registration, a registry one included.

One rule the reconciler keeps, about not undoing a person: it never re-enables
a registration an operator disabled — deactivating an app is the
incident-response lever, so a restart must not quietly reverse it.

Everything here runs on the system engine: ``app_service_registrations`` has no
request-path write grant.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence
from urllib.parse import urlparse

from fastapi import HTTPException, status as http_status
from jwt import PyJWK
from jwt.exceptions import InvalidKeyError, PyJWKError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_scopes import UnknownAppScope, validate_scopes
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.messages import AppServiceMessages
from app.core.security import app_platform_signing_enabled
from app.models.platform.app_service_registration import (
    MAX_APP_ID_LENGTH,
    AppServiceRegistration,
    RegistrationSource,
)
from app.models.platform.marketplace import UID_ALPHABET, UID_LENGTH
from app.models.platform.publisher import Publisher, publisher_prefix
from app.services import audit as audit_service
from app.services.marketplace.app_keys import (
    PRIVATE_JWK_MEMBERS,
    PUBLIC_JWK_TYPES,
    jwks_uri_allowed,
)
from app.services.marketplace import vendor_values as vendor_values_service
from app.services.marketplace.publishers import ensure_publisher
from app.services.marketplace.registration_lookup import (
    invalidate_registrations,
    live_registration_clause,
)
from app.core.clock import utcnow

logger = logging.getLogger(__name__)

#: What a registration confers and where it points, for the record.
AUDITED_FIELDS: tuple[str, ...] = (
    "public_id",
    "listing_uid",
    "publisher_id",
    "base_url",
    "embed_origin",
    "allowed_origins",
    "jwks_uri",
    "scope_ceiling",
    "mandatory",
    "enabled",
    "source",
    "image_digest",
    "reference_sectors",
)


__all__ = [
    "ReconcileResult",
    "RegistrationView",
    "RegistryFacts",
    "apply_registry_facts",
    "check_signing_configured",
    "create_registration",
    "delete_registration",
    "get_registration",
    "is_registry_container",
    "row_browser_base",
    "list_registrations",
    "normalize_base_url",
    "normalize_jwks",
    "normalize_jwks_uri",
    "normalize_embed_origin",
    "normalize_listing_uid",
    "normalize_origin",
    "normalize_origins",
    "normalize_public_id",
    "normalize_scope_ceiling",
    "origin_of",
    "reconcile_from_config",
    "registration_views",
    "registry_facts",
    "update_registration",
]

#: Characters a ``public_id`` may use: ``<publisher>.<slug>``, lowercase — the
#: same shape the catalog requires, checked as an explicit set so a stored id is
#: exactly what a URL and a JWT audience will carry.
_PUBLIC_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-_")
_MAX_PUBLIC_ID = MAX_APP_ID_LENGTH
_MAX_BASE_URL = 1000
_MAX_ORIGIN = 253 + 16
_MAX_ORIGINS = 20


def _bad_request(code: str, detail: str) -> HTTPException:
    logger.debug("app service registration refused (%s): %s", code, detail)
    return HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=code)


def is_registry_container(row: AppServiceRegistration) -> bool:
    """Whether the registry brought this row as a container the operator runs."""
    return row.source == RegistrationSource.REGISTRY and row.image_digest is not None


def row_browser_base(row: AppServiceRegistration) -> Optional[str]:
    """Where a browser loads the app's surfaces, or ``None`` for a registry
    container that has no location yet."""
    return row.embed_origin or row.base_url


def _registry_managed() -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_409_CONFLICT,
        detail=AppServiceMessages.REGISTRY_MANAGED,
    )


# --- validation --------------------------------------------------------------


def check_signing_configured() -> None:
    """Refuse to run the app platform without its own signing key.

    The keypair is required and has no fallback to any other configured key, so
    an unset one is reported as configuration rather than silently substituted.
    """
    if not app_platform_signing_enabled():
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AppServiceMessages.SIGNING_NOT_CONFIGURED,
        )


def normalize_public_id(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if not cleaned or len(cleaned) > _MAX_PUBLIC_ID:
        raise _bad_request(
            AppServiceMessages.INVALID_PUBLIC_ID,
            f"public_id must be 1..{_MAX_PUBLIC_ID} characters",
        )
    for char in cleaned:
        if char not in _PUBLIC_ID_CHARS:
            raise _bad_request(
                AppServiceMessages.INVALID_PUBLIC_ID,
                f"public_id contains {char!r}, which is not allowed",
            )
    if "." not in cleaned:
        raise _bad_request(
            AppServiceMessages.INVALID_PUBLIC_ID,
            "public_id must be '<publisher>.<slug>'",
        )
    return cleaned


def _normalize_url_base(value: str, *, code: str, field: str) -> str:
    """A base URL is a scheme, a host, an optional port, and an optional path
    prefix — nothing else. The egress policy (scheme vs address class) is
    applied when the connection is actually made, by ``safe_http``.
    """
    cleaned = (value or "").strip().rstrip("/")
    if not cleaned or len(cleaned) > _MAX_BASE_URL:
        raise _bad_request(code, f"{field} must be 1..{_MAX_BASE_URL} characters")
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise _bad_request(code, f"{field} must be http or https")
    if not parsed.hostname:
        raise _bad_request(code, f"{field} needs a host")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise _bad_request(code, f"{field} carries no query, fragment, or credentials")
    return cleaned


def normalize_base_url(value: str) -> str:
    """Where Initiative's own server calls this app."""
    return _normalize_url_base(
        value, code=AppServiceMessages.INVALID_BASE_URL, field="base_url"
    )


def normalize_embed_origin(value: str) -> str:
    """Where a person's browser loads this app's surfaces.

    Held to the same shape as ``base_url`` because it stands in for it: the
    manifest declares one path per surface, and it is joined to whichever of the
    two addresses the reader is on. A deployment that publishes its apps under a
    path prefix can therefore say so here as well.
    """
    return _normalize_url_base(
        value, code=AppServiceMessages.INVALID_EMBED_ORIGIN, field="embed_origin"
    )


def origin_of(base: str) -> str:
    """The origin half of an already-normalized base URL.

    A base may carry a path prefix and an origin never does, so the prefix is
    dropped here rather than refused — this reads a value the service itself
    validated, not something a person typed.
    """
    parsed = urlparse(base)
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def normalize_origin(value: str) -> str:
    """An allowed origin is ``scheme://host[:port]`` and nothing more — a path
    or a wildcard would widen it beyond what an origin comparison can honor."""
    cleaned = (value or "").strip().rstrip("/")
    if not cleaned or len(cleaned) > _MAX_ORIGIN:
        raise _bad_request(
            AppServiceMessages.INVALID_ORIGIN, "origin has an unusable length"
        )
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise _bad_request(
            AppServiceMessages.INVALID_ORIGIN,
            "origin must be 'scheme://host[:port]'",
        )
    if parsed.path or parsed.query or parsed.fragment:
        raise _bad_request(
            AppServiceMessages.INVALID_ORIGIN, "origin carries no path or query"
        )
    return origin_of(cleaned)


def normalize_origins(
    values: Optional[Iterable[str]], *, browser_base: str
) -> list[str]:
    """Canonicalize the origin list, defaulting to the browser base's own origin.

    Derived from the browser base rather than the wire surface because these are
    browser origins: what a document may frame, and what the SPA posts to.
    """
    items = [v for v in (values or []) if isinstance(v, str) and v.strip()]
    if not items:
        return [origin_of(browser_base)]
    if len(items) > _MAX_ORIGINS:
        raise _bad_request(
            AppServiceMessages.INVALID_ORIGIN,
            f"at most {_MAX_ORIGINS} origins per registration",
        )
    normalized: list[str] = []
    for item in items:
        origin = normalize_origin(item)
        if origin not in normalized:
            normalized.append(origin)
    return normalized


def normalize_jwks(value: Optional[dict]) -> Optional[dict]:
    """Check an app's key set holds public verification keys, each carrying
    the ``kid`` a JWT names.

    The set is the app's client credential: the token endpoint verifies the
    assertions it signs against it. A registration with neither this set nor
    a ``jwks_uri`` is not live.

    Parsed on the way in rather than at first use, so an operator provisioning
    a key learns here whether it landed instead of at the first call that
    needs it. An empty object clears the set.

    Held to public asymmetric keys only. This column is served in full to the
    owner's settings, which is right for a public half and wrong for anything
    else, so a key carrying private members or a shared symmetric value is
    refused rather than stored — the paste is a mistake worth naming at the
    moment it happens.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _bad_request(
            AppServiceMessages.INVALID_JWKS,
            "expected a JWKS object",
        )
    if not value:
        return None

    keys = value.get("keys")
    if not isinstance(keys, list) or not keys:
        raise _bad_request(
            AppServiceMessages.INVALID_JWKS,
            "expected {'keys': [...]} holding at least one key",
        )

    seen: set[str] = set()
    for entry in keys:
        if not isinstance(entry, dict):
            raise _bad_request(
                AppServiceMessages.INVALID_JWKS,
                "every entry in 'keys' must be an object",
            )
        kid = entry.get("kid")
        if not isinstance(kid, str) or not kid.strip():
            raise _bad_request(
                AppServiceMessages.INVALID_JWKS,
                "every key needs a 'kid' — a token names one to select it",
            )
        if kid in seen:
            raise _bad_request(
                AppServiceMessages.INVALID_JWKS,
                f"two keys share the kid {kid!r}",
            )
        seen.add(kid)
        if entry.get("kty") not in PUBLIC_JWK_TYPES:
            raise _bad_request(
                AppServiceMessages.INVALID_JWKS,
                f"key {kid!r} is not a public key type "
                f"({', '.join(sorted(PUBLIC_JWK_TYPES))})",
            )
        private = sorted(PRIVATE_JWK_MEMBERS.intersection(entry))
        if private:
            raise _bad_request(
                AppServiceMessages.INVALID_JWKS,
                f"key {kid!r} carries private material ({', '.join(private)}) — "
                "provision the public half",
            )
        try:
            PyJWK.from_dict(entry)
        except (PyJWKError, InvalidKeyError, KeyError, TypeError, ValueError) as exc:
            raise _bad_request(
                AppServiceMessages.INVALID_JWKS,
                f"key {kid!r} is unusable: {exc}",
            ) from exc

    return value


def normalize_listing_uid(value: Optional[str]) -> str:
    """The catalog uid of the listing a registration speaks for: required, and
    held to the catalog's own alphabet and length."""
    cleaned = (value or "").strip()
    if len(cleaned) != UID_LENGTH or any(c not in UID_ALPHABET for c in cleaned):
        raise _bad_request(
            AppServiceMessages.INVALID_LISTING_UID,
            f"listing_uid must be a {UID_LENGTH}-character catalog uid",
        )
    return cleaned


def normalize_jwks_uri(value: Optional[str], *, base_url: str) -> Optional[str]:
    """Where the app publishes its key set: https, on ``base_url``'s own
    origin, with no query, fragment or credentials. Empty clears it."""
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > _MAX_BASE_URL:
        raise _bad_request(
            AppServiceMessages.INVALID_JWKS_URI, "jwks_uri has an unusable length"
        )
    parsed = urlparse(cleaned)
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise _bad_request(
            AppServiceMessages.INVALID_JWKS_URI,
            "jwks_uri carries no query, fragment, or credentials",
        )
    if not jwks_uri_allowed(cleaned, base_url):
        raise _bad_request(
            AppServiceMessages.INVALID_JWKS_URI,
            "jwks_uri must be https on base_url's own origin",
        )
    return cleaned


def normalize_scope_ceiling(values: Optional[Iterable[str]]) -> list[str]:
    """Check a scope ceiling against the app scope vocabulary.

    The ceiling is the most any install of this app may be granted, so every
    entry must be a scope ``app.core.app_scopes`` defines. An unknown one is
    refused rather than stored. Returned sorted and without repeats, so one set
    has one stored form.
    """
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise _bad_request(
            AppServiceMessages.UNKNOWN_SCOPE, "scope_ceiling must be a list"
        )
    entries = list(values)
    for value in entries:
        if not isinstance(value, str):
            raise _bad_request(
                AppServiceMessages.UNKNOWN_SCOPE, f"{value!r} is not a scope"
            )
    try:
        checked = validate_scopes(entries)
    except UnknownAppScope as exc:
        raise _bad_request(
            AppServiceMessages.UNKNOWN_SCOPE, f"{exc.scope!r} is not a scope"
        ) from exc
    return sorted(checked)


# --- reads -------------------------------------------------------------------


async def list_registrations(
    session: AsyncSession,
) -> Sequence[AppServiceRegistration]:
    result = await session.exec(
        select(AppServiceRegistration).order_by(AppServiceRegistration.public_id.asc())
    )
    return result.all()


@dataclass(frozen=True)
class RegistrationView:
    """A registration with its publisher, and whether it is live."""

    row: AppServiceRegistration
    publisher: Publisher
    live: bool


async def registration_views(
    session: AsyncSession, registration_id: Optional[int] = None
) -> list[RegistrationView]:
    """Every registration, or the one ``registration_id`` names, each with its
    publisher and whether it is live, in one statement."""
    query = (
        select(AppServiceRegistration, Publisher, live_registration_clause())
        .join(Publisher, Publisher.id == AppServiceRegistration.publisher_id)
        .order_by(AppServiceRegistration.public_id.asc())
    )
    if registration_id is not None:
        query = query.where(AppServiceRegistration.id == registration_id)
    rows = (await session.exec(query)).all()
    return [
        RegistrationView(row=row, publisher=publisher, live=bool(live))
        for row, publisher, live in rows
    ]


async def get_registration(
    session: AsyncSession, registration_id: int
) -> AppServiceRegistration:
    row = await session.get(AppServiceRegistration, registration_id)
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=AppServiceMessages.NOT_FOUND,
        )
    return row


async def _by_public_id(
    session: AsyncSession, public_id: str
) -> Optional[AppServiceRegistration]:
    result = await session.exec(
        select(AppServiceRegistration).where(
            AppServiceRegistration.public_id == public_id
        )
    )
    return result.first()


# --- writes ------------------------------------------------------------------


async def create_registration(
    session: AsyncSession,
    *,
    public_id: str,
    listing_uid: str,
    base_url: str,
    embed_origin: Optional[str] = None,
    allowed_origins: Optional[Iterable[str]] = None,
    jwks: Optional[dict] = None,
    jwks_uri: Optional[str] = None,
    scope_ceiling: Optional[Iterable[str]] = None,
    mandatory: bool = False,
    enabled: bool = True,
    vendor_values: Optional[dict[str, Optional[str]]] = None,
    actor_user_id: int | None = None,
) -> AppServiceRegistration:
    """Wire an app service up, as stated.

    Nothing is fetched from the app: the operator names it, its listing, its
    addresses and its keys. Its publisher is the row for its prefix, added
    unverified when there is none.
    """
    check_signing_configured()
    resolved_id = normalize_public_id(public_id)
    uid = normalize_listing_uid(listing_uid)
    base_url = normalize_base_url(base_url)
    embed = normalize_embed_origin(embed_origin) if embed_origin else None
    origins = normalize_origins(allowed_origins, browser_base=embed or base_url)
    key_set = normalize_jwks(jwks)
    key_uri = normalize_jwks_uri(jwks_uri, base_url=base_url)
    ceiling = normalize_scope_ceiling(scope_ceiling)

    if await _by_public_id(session, resolved_id) is not None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=AppServiceMessages.DUPLICATE_PUBLIC_ID,
        )
    publisher = await ensure_publisher(session, publisher_prefix(resolved_id))

    row = AppServiceRegistration(
        public_id=resolved_id,
        listing_uid=uid,
        publisher_id=publisher.id,
        base_url=base_url,
        embed_origin=embed,
        allowed_origins=origins,
        jwks=key_set,
        jwks_uri=key_uri,
        scope_ceiling=ceiling,
        mandatory=mandatory,
        enabled=enabled,
    )
    vendor_changed = await _apply_vendor(session, row, vendor_values)
    await vendor_values_service.sync_required(session, row)
    session.add(row)
    await session.flush()
    await audit_service.record(
        session,
        event_type=AuditEventType.APP_SERVICE_CREATED,
        actor_user_id=actor_user_id,
        target_type="app_service_registration",
        target_id=row.id,
        detail={
            **audit_service.changed_fields(
                {}, audit_service.snapshot(row, AUDITED_FIELDS)
            ),
            **({"vendor_values": vendor_changed} if vendor_changed else {}),
        },
    )
    await session.commit()
    await session.refresh(row)
    invalidate_registrations()
    return row


async def _apply_vendor(
    session: AsyncSession,
    row: AppServiceRegistration,
    submitted: Optional[dict[str, Optional[str]]],
) -> list[str]:
    """Set the vendor values the form sent, against the fields the listing's
    manifest declares. Returns the keys that changed, never their values."""
    if not submitted:
        return []
    definitions = await vendor_values_service.listing_definitions(
        session, [row.listing_uid]
    )
    return vendor_values_service.apply_vendor_values(
        row, submitted, definition=definitions.get(row.listing_uid or "")
    )


async def update_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    listing_uid: Optional[str] = None,
    base_url: Optional[str] = None,
    embed_origin: Optional[str] = None,
    allowed_origins: Optional[Iterable[str]] = None,
    jwks: Optional[dict] = None,
    jwks_uri: Optional[str] = None,
    scope_ceiling: Optional[Iterable[str]] = None,
    mandatory: Optional[bool] = None,
    enabled: Optional[bool] = None,
    vendor_values: Optional[dict[str, Optional[str]]] = None,
    actor_user_id: int | None = None,
) -> AppServiceRegistration:
    """Edit a registration.

    An empty ``embed_origin`` clears it, putting both surfaces back on
    ``base_url``; an empty ``jwks_uri`` clears it. A ``jwks_uri`` kept while
    ``base_url`` moves is checked against the new origin.

    A registration the registry brought takes only the operator's fields (the
    switch, mandatory flag, origins, a container's location and keys, and its
    vendor values); a change to anything else answers 409.
    """
    row = await get_registration(session, registration_id)
    if row.source == RegistrationSource.REGISTRY:
        _check_registry_edit(
            row,
            listing_uid=listing_uid,
            base_url=base_url,
            embed_origin=embed_origin,
            jwks=jwks,
            jwks_uri=jwks_uri,
            scope_ceiling=scope_ceiling,
        )
    before = audit_service.snapshot(row, AUDITED_FIELDS)
    if listing_uid is not None:
        row.listing_uid = normalize_listing_uid(listing_uid)
    _write_placement(
        row,
        base_url=base_url,
        embed_origin=embed_origin,
        allowed_origins=allowed_origins,
        jwks=jwks,
        jwks_uri=jwks_uri,
    )
    if scope_ceiling is not None:
        # Replaces rather than merges; an empty list is a ceiling of nothing.
        row.scope_ceiling = normalize_scope_ceiling(scope_ceiling)
    if mandatory is not None:
        row.mandatory = mandatory
    if enabled is not None:
        row.enabled = enabled
    vendor_changed = await _apply_vendor(session, row, vendor_values)
    await vendor_values_service.sync_required(session, row)

    row.updated_at = utcnow()
    session.add(row)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, AUDITED_FIELDS)
    )
    if vendor_changed:
        # Which values moved, by key. A value is the vendor client's
        # credential, so none of it reaches the record.
        changed = {**changed, "vendor_values": vendor_changed}
    if changed["changed"] or vendor_changed:
        await audit_service.record(
            session,
            event_type=AuditEventType.APP_SERVICE_UPDATED,
            actor_user_id=actor_user_id,
            target_type="app_service_registration",
            target_id=row.id,
            detail=changed,
        )
    await session.commit()
    await session.refresh(row)
    # The kill switch, the mandatory flag, the keys and the origin list are all
    # read through a cached snapshot on the request path, so an operator's edit
    # drops it rather than waiting out its TTL.
    invalidate_registrations()
    return row


def _write_placement(
    row: AppServiceRegistration,
    *,
    base_url: Optional[str],
    embed_origin: Optional[str],
    allowed_origins: Optional[Iterable[str]],
    jwks: Optional[dict],
    jwks_uri: Optional[str],
) -> None:
    """Write where an app runs, the origins that may frame it, and its keys.

    ``None`` leaves a field as it is; an empty ``embed_origin``, ``jwks`` or
    ``jwks_uri`` clears it.
    """
    # Whether the origin list is still just the app's own origin. An untouched
    # list follows the address it was derived from; one an operator typed is
    # theirs and is left exactly as typed. A container with no location yet
    # has no origin of its own, so its empty list counts as untouched.
    current_base = row_browser_base(row)
    origins_were_default = (
        list(row.allowed_origins or []) == [origin_of(current_base)]
        if current_base
        else not row.allowed_origins
    )

    if base_url is not None:
        row.base_url = normalize_base_url(base_url)
    if embed_origin is not None:
        cleaned = embed_origin.strip()
        row.embed_origin = normalize_embed_origin(cleaned) if cleaned else None
    new_base = row_browser_base(row)
    if allowed_origins is not None:
        if new_base is None:
            # Nothing to derive a default from, and nothing to frame yet.
            row.allowed_origins = [normalize_origin(item) for item in allowed_origins]
        else:
            row.allowed_origins = normalize_origins(
                allowed_origins, browser_base=new_base
            )
    elif origins_were_default and new_base is not None:
        row.allowed_origins = normalize_origins(None, browser_base=new_base)
    if jwks is not None:
        # Replaces rather than merges, and an empty object clears: a key set is
        # provisioned whole, so two entries mean a rotation is in flight and
        # one means it is over.
        row.jwks = normalize_jwks(jwks)
    if jwks_uri is not None and row.base_url is not None:
        row.jwks_uri = normalize_jwks_uri(jwks_uri, base_url=row.base_url)
    elif row.jwks_uri is not None and base_url is not None and row.base_url:
        row.jwks_uri = normalize_jwks_uri(row.jwks_uri, base_url=row.base_url)


def _check_registry_edit(
    row: AppServiceRegistration,
    *,
    listing_uid: Optional[str],
    base_url: Optional[str],
    embed_origin: Optional[str],
    jwks: Optional[dict],
    jwks_uri: Optional[str],
    scope_ceiling: Optional[Iterable[str]],
) -> None:
    """Refuse a change to what the registry says about an app.

    A value sent unchanged is not a change, so a form that sends every field
    back saves the operator's own edits. A container's location and keys are
    the operator's to give: the deployment runs it and holds its private key.
    """
    changes: list[str] = []
    if listing_uid is not None and listing_uid.strip() != (row.listing_uid or ""):
        changes.append("listing_uid")
    if scope_ceiling is not None and normalize_scope_ceiling(scope_ceiling) != sorted(
        row.scope_ceiling or []
    ):
        changes.append("scope_ceiling")
    if not is_registry_container(row):
        if jwks is not None and normalize_jwks(jwks) != row.jwks:
            changes.append("jwks")
        if jwks_uri is not None and (jwks_uri.strip() or None) != row.jwks_uri:
            changes.append("jwks_uri")
        if base_url is not None and normalize_base_url(base_url) != row.base_url:
            changes.append("base_url")
        if embed_origin is not None:
            cleaned = embed_origin.strip()
            wanted = normalize_embed_origin(cleaned) if cleaned else None
            if wanted != row.embed_origin:
                changes.append("embed_origin")
    if changes:
        logger.debug(
            "app service registration %s: the registry keeps %s",
            row.public_id,
            ", ".join(changes),
        )
        raise _registry_managed()


async def delete_registration(
    session: AsyncSession, registration_id: int, *, actor_user_id: int | None = None
) -> None:
    """Remove a registration. One the registry brought is switched off instead
    (409): the next refresh would bring it back."""
    row = await get_registration(session, registration_id)
    if row.source == RegistrationSource.REGISTRY:
        raise _registry_managed()
    await session.delete(row)
    await audit_service.record(
        session,
        event_type=AuditEventType.APP_SERVICE_DELETED,
        actor_user_id=actor_user_id,
        target_type="app_service_registration",
        target_id=registration_id,
        detail={},
    )
    await session.commit()
    invalidate_registrations()


# --- boot reconciliation -----------------------------------------------------


@dataclass(frozen=True)
class ReconcileResult:
    """What one pass over ``APP_SERVICES_CONFIG`` did."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged + self.skipped


def _load_entries(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(document, dict):
        document = document.get("app_services", [])
    if not isinstance(document, list):
        raise ValueError("expected a JSON array of app service entries")
    return [entry for entry in document if isinstance(entry, dict)]


#: What an entry marked ``"registry": true`` may not state: the registry does.
_REGISTRY_STATES = ("listing_uid", "scope_ceiling", "image", "image_digest")


@dataclass(frozen=True)
class RegistryFacts:
    """How this deployment runs an app the registry brings, from an
    ``APP_SERVICES_CONFIG`` entry marked ``"registry": true``.

    ``None`` is a fact the entry leaves out, which leaves the row's value as
    it is. A container's placement is one statement: an entry that gives its
    ``base_url`` gives its browser address and keys with it, and clears the
    ones it leaves out.
    """

    base_url: Optional[str] = None
    embed_origin: Optional[str] = None
    jwks: Optional[dict] = None
    jwks_uri: Optional[str] = None
    allowed_origins: Optional[list[str]] = None
    mandatory: Optional[bool] = None
    vendor_env: Any = None

    @property
    def places(self) -> bool:
        """Whether it gives a location and keys, which only a container takes."""
        return self.base_url is not None


def _registry_facts(entry: dict[str, Any]) -> RegistryFacts:
    """Read an entry marked ``"registry": true``, refusing one that states
    what the registry says about the app, or a location or keys that do not
    fit together."""
    stated = [key for key in _REGISTRY_STATES if key in entry]
    if stated:
        raise _bad_request(
            AppServiceMessages.REGISTRY_MANAGED,
            f"the registry states {', '.join(stated)}",
        )
    declared_base = entry.get("base_url")
    base_url = normalize_base_url(str(declared_base)) if declared_base else None
    if base_url is None and any(
        entry.get(key) for key in ("embed_origin", "jwks", "jwks_uri")
    ):
        raise _bad_request(
            AppServiceMessages.INVALID_BASE_URL,
            "a container's browser address and keys come with its base_url",
        )
    declared_origins = entry.get("allowed_origins") or []
    if not isinstance(declared_origins, list) or len(declared_origins) > _MAX_ORIGINS:
        raise _bad_request(
            AppServiceMessages.INVALID_ORIGIN,
            f"allowed_origins must be a list of at most {_MAX_ORIGINS} origins",
        )
    origins = [normalize_origin(str(item)) for item in declared_origins]
    declared_embed = entry.get("embed_origin")
    declared_uri = entry.get("jwks_uri")
    return RegistryFacts(
        base_url=base_url,
        embed_origin=(
            normalize_embed_origin(str(declared_embed)) if declared_embed else None
        ),
        jwks=normalize_jwks(entry.get("jwks")),
        jwks_uri=(
            normalize_jwks_uri(str(declared_uri), base_url=base_url or "")
            if declared_uri
            else None
        ),
        allowed_origins=origins or None,
        mandatory=bool(entry["mandatory"]) if "mandatory" in entry else None,
        vendor_env=entry.get("vendor_env"),
    )


def registry_facts(public_id: str) -> Optional[RegistryFacts]:
    """The facts ``APP_SERVICES_CONFIG`` gives for the registry's app
    ``public_id``, or ``None``.

    Read when the registry refresh applies the app, so facts written before
    the registry brought it reach its row. An entry reconciliation refuses
    gives nothing here either.
    """
    configured = settings.APP_SERVICES_CONFIG
    if not configured:
        return None
    try:
        entries = _load_entries(Path(configured))
    except (OSError, ValueError):
        return None
    for entry in entries:
        if entry.get("registry") is not True:
            continue
        if str(entry.get("public_id", "")).strip().lower() != public_id:
            continue
        try:
            return _registry_facts(entry)
        except HTTPException:
            continue
    return None


def apply_registry_facts(row: AppServiceRegistration, facts: RegistryFacts) -> bool:
    """Write an entry's facts onto a registry row, and say whether any moved.

    Never changes the row's source. A container takes its placement from them;
    a hosted app's location and keys stay the registry's, so facts giving
    them are passed over. Vendor values are sealed from the environment
    variables the entry names.
    """

    def state() -> tuple:
        return (
            row.base_url,
            row.embed_origin,
            list(row.allowed_origins or []),
            row.jwks,
            row.jwks_uri,
            row.mandatory,
        )

    was = state()
    placed = facts.places and is_registry_container(row)
    if facts.places and not placed:
        logger.warning(
            "app services: %r is hosted by its publisher, whose location and "
            "keys it keeps; the entry's are passed over",
            row.public_id,
        )
    _write_placement(
        row,
        base_url=facts.base_url if placed else None,
        embed_origin=(facts.embed_origin or "") if placed else None,
        allowed_origins=facts.allowed_origins,
        jwks=(facts.jwks or {}) if placed else None,
        jwks_uri=(facts.jwks_uri or "") if placed else None,
    )
    if facts.mandatory is not None:
        row.mandatory = facts.mandatory
    vendor_moved = vendor_values_service.apply_vendor_env(
        row, facts.vendor_env, public_id=row.public_id
    )
    return bool(vendor_moved) or state() != was


async def reconcile_from_config(session: AsyncSession) -> ReconcileResult:
    """Bring the table in line with the mounted config file.

    Each entry is ``{public_id, listing_uid, base_url}`` and optionally
    ``embed_origin``, ``allowed_origins``, ``jwks``, ``jwks_uri``,
    ``scope_ceiling``, ``mandatory`` and ``vendor_env`` (vendor key →
    environment variable name, read and sealed on every pass). Database-only:
    this upserts rows and stops.

    An entry marked ``"registry": true`` is :class:`RegistryFacts` for an app
    the registry brings, written onto its row without changing its source.
    It creates nothing: before the registry brings the app, the refresh that
    does applies them. It is refused when an operator's registration holds
    that ``public_id``, and when it gives a hosted app a location or keys.

    An entry naming ``grants`` is read without it, and the pass logs that it
    was: the field is no longer part of a registration, and a file written for
    an earlier release still boots.

    A malformed file or an unreadable path costs that file, and a refused entry
    costs that entry, and nothing else — the caller keeps booting.
    """
    configured = settings.APP_SERVICES_CONFIG
    if not configured:
        return ReconcileResult()

    path = Path(configured)
    try:
        entries = _load_entries(path)
    except (OSError, ValueError) as exc:
        logger.warning("app services: %s could not be read (%s)", path, exc)
        return ReconcileResult()

    created = updated = unchanged = skipped = 0
    # The rows this pass touched, with what the updated ones looked like
    # before. Recorded after the loop, when the inserts have their ids.
    born: list[AppServiceRegistration] = []
    edited: list[tuple[AppServiceRegistration, dict]] = []
    # A public_id already handled in this pass. The row for it is pending rather
    # than flushed, so a second entry naming it would look absent, insert a
    # duplicate, and fail the unique constraint at the shared commit — taking
    # every other registration in the file down with it.
    seen: set[str] = set()

    def first_mention(public_id: str) -> bool:
        if public_id in seen:
            logger.warning(
                "app services: %r appears more than once in %s — later entry skipped",
                public_id,
                path,
            )
            return False
        seen.add(public_id)
        return True

    for entry in entries:
        if entry.get("registry") is True:
            try:
                public_id = normalize_public_id(str(entry.get("public_id", "")))
                facts = _registry_facts(entry)
            except HTTPException as exc:
                logger.warning(
                    "app services: entry %r refused (%s)",
                    entry.get("public_id"),
                    exc.detail,
                )
                skipped += 1
                continue
            if not first_mention(public_id):
                skipped += 1
                continue
            row = await _by_public_id(session, public_id)
            if row is None:
                logger.info(
                    "app services: %r is not here yet; the registry refresh that "
                    "brings it applies its entry",
                    public_id,
                )
                unchanged += 1
                continue
            if row.source != RegistrationSource.REGISTRY:
                logger.warning(
                    "app services: this deployment's operator registered %r; its "
                    "registry entry is refused",
                    public_id,
                )
                skipped += 1
                continue
            if facts.places and not is_registry_container(row):
                logger.warning(
                    "app services: %r is hosted by its publisher, whose location "
                    "and keys it keeps; its registry entry is refused",
                    public_id,
                )
                skipped += 1
                continue
            before = audit_service.snapshot(row, AUDITED_FIELDS)
            required_before = list(row.vendor_required or [])
            moved = apply_registry_facts(row, facts)
            await vendor_values_service.sync_required(session, row)
            if not moved and required_before == list(row.vendor_required or []):
                unchanged += 1
                continue
            row.updated_at = utcnow()
            session.add(row)
            edited.append((row, before))
            updated += 1
            continue

        try:
            public_id = normalize_public_id(str(entry.get("public_id", "")))
            listing_uid = normalize_listing_uid(str(entry.get("listing_uid") or ""))
            base_url = normalize_base_url(str(entry.get("base_url", "")))
            declared_embed = entry.get("embed_origin")
            embed = (
                normalize_embed_origin(str(declared_embed)) if declared_embed else None
            )
            origins = normalize_origins(
                entry.get("allowed_origins"), browser_base=embed or base_url
            )
            key_set = normalize_jwks(entry.get("jwks"))
            declared_uri = entry.get("jwks_uri")
            key_uri = normalize_jwks_uri(
                str(declared_uri) if declared_uri else None, base_url=base_url
            )
            # Optional: an entry that names none gives the app a ceiling of
            # nothing, so no install of it may be granted a scope.
            ceiling = normalize_scope_ceiling(entry.get("scope_ceiling"))
        except HTTPException as exc:
            logger.warning(
                "app services: entry %r refused (%s)",
                entry.get("public_id"),
                exc.detail,
            )
            skipped += 1
            continue
        if "grants" in entry:
            logger.warning(
                "app services: entry %r names grants, which a registration no "
                "longer has; the field is ignored",
                public_id,
            )

        if not first_mention(public_id):
            skipped += 1
            continue

        mandatory = bool(entry.get("mandatory", False))
        row = await _by_public_id(session, public_id)
        if row is None:
            publisher = await ensure_publisher(session, publisher_prefix(public_id))
            fresh = AppServiceRegistration(
                public_id=public_id,
                listing_uid=listing_uid,
                publisher_id=publisher.id,
                base_url=base_url,
                embed_origin=embed,
                allowed_origins=origins,
                jwks=key_set,
                jwks_uri=key_uri,
                scope_ceiling=ceiling,
                mandatory=mandatory,
                enabled=True,
            )
            vendor_values_service.apply_vendor_env(
                fresh, entry.get("vendor_env"), public_id=public_id
            )
            await vendor_values_service.sync_required(session, fresh)
            session.add(fresh)
            born.append(fresh)
            created += 1
            continue

        # The file is the declarative source for what the app IS and may do.
        # `enabled` is deliberately not reconciled: turning a registration off
        # is an operator action, and a restart must not reverse it. A row the
        # registry brought becomes the operator's: an entry without the
        # registry mark is their statement of the whole app, and it wins.
        taken_over = row.source == RegistrationSource.REGISTRY
        vendor_moved = vendor_values_service.apply_vendor_env(
            row, entry.get("vendor_env"), public_id=public_id
        )
        required_before = list(row.vendor_required or [])
        await vendor_values_service.sync_required(session, row)
        dirty = (
            taken_over
            or bool(vendor_moved)
            or required_before != list(row.vendor_required or [])
            or listing_uid != row.listing_uid
            or base_url != row.base_url
            or embed != row.embed_origin
            or origins != list(row.allowed_origins or [])
            or key_set != row.jwks
            or key_uri != row.jwks_uri
            or ceiling != list(row.scope_ceiling or [])
            or mandatory != row.mandatory
        )
        if not dirty:
            unchanged += 1
            continue

        before = audit_service.snapshot(row, AUDITED_FIELDS)
        row.listing_uid = listing_uid
        row.base_url = base_url
        row.embed_origin = embed
        row.allowed_origins = origins
        row.jwks = key_set
        row.jwks_uri = key_uri
        row.scope_ceiling = ceiling
        row.mandatory = mandatory
        if taken_over:
            row.source = RegistrationSource.OPERATOR
            row.image_digest = None
            row.reference_sectors = []
            row.root_is_builtin = False
        row.updated_at = utcnow()
        session.add(row)
        edited.append((row, before))
        updated += 1

    # One flush so every insert has its id, then a record apiece. The file is
    # the author, so the rows carry no actor.
    if born or edited:
        await session.flush()
    for fresh in born:
        await audit_service.record(
            session,
            event_type=AuditEventType.APP_SERVICE_CREATED,
            actor_user_id=None,
            target_type="app_service_registration",
            target_id=fresh.id,
            detail={
                "via": "config",
                **audit_service.changed_fields(
                    {}, audit_service.snapshot(fresh, AUDITED_FIELDS)
                ),
            },
        )
    for edit, was in edited:
        await audit_service.record(
            session,
            event_type=AuditEventType.APP_SERVICE_UPDATED,
            actor_user_id=None,
            target_type="app_service_registration",
            target_id=edit.id,
            detail={
                "via": "config",
                **audit_service.changed_fields(
                    was, audit_service.snapshot(edit, AUDITED_FIELDS)
                ),
            },
        )
    await session.commit()
    invalidate_registrations()
    return ReconcileResult(
        created=created, updated=updated, unchanged=unchanged, skipped=skipped
    )
