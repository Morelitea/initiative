"""Managing the deployment's app service registrations.

Two ways a registration arrives, and they meet in the same checks:

* **An operator adds one** through the ``apps.manage`` endpoints.
* **The deployment declares them** in ``APP_SERVICES_CONFIG``, a file a chart
  mounts, reconciled at boot. Reconciliation touches the database only, so a
  boot never waits on an app's container.

Either way the registration states everything about itself: its
``public_id``, the ``listing_uid`` of the listing it speaks for, where it
lives, and its public keys (a pasted key set, a ``jwks_uri`` on its own
origin, or both). Nothing is fetched from the app to fill any of it in, and
nothing is secret. Its publisher is the row for its ``public_id`` prefix
(:mod:`app.services.marketplace.publishers`).

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
from datetime import datetime, timezone
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
    APP_SERVICE_GRANTS,
    MAX_APP_ID_LENGTH,
    AppServiceRegistration,
    browser_base,
)
from app.models.platform.marketplace import UID_ALPHABET, UID_LENGTH
from app.models.platform.publisher import Publisher, publisher_prefix
from app.services import audit as audit_service
from app.services.marketplace.app_keys import (
    PRIVATE_JWK_MEMBERS,
    PUBLIC_JWK_TYPES,
    jwks_uri_allowed,
)
from app.services.marketplace.publishers import ensure_publisher
from app.services.marketplace.registration_lookup import (
    invalidate_registrations,
    live_registration_clause,
)

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
    "grants",
    "scope_ceiling",
    "mandatory",
    "enabled",
)

__all__ = [
    "ReconcileResult",
    "RegistrationView",
    "check_signing_configured",
    "create_registration",
    "delete_registration",
    "get_registration",
    "list_registrations",
    "normalize_base_url",
    "normalize_jwks",
    "normalize_jwks_uri",
    "normalize_embed_origin",
    "normalize_grants",
    "normalize_listing_uid",
    "normalize_origin",
    "normalize_origins",
    "normalize_public_id",
    "normalize_scope_ceiling",
    "origin_of",
    "reconcile_from_config",
    "registration_views",
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _bad_request(code: str, detail: str) -> HTTPException:
    logger.debug("app service registration refused (%s): %s", code, detail)
    return HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=code)


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
    assertions it signs against it, and the delegation path its delegation
    tokens. So it is kept whatever the registration's grants are. A
    registration with neither this set nor a ``jwks_uri`` is not live.

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


def normalize_grants(values: Optional[Iterable[str]]) -> list[str]:
    """Check operator-conferred powers against the closed vocabulary.

    A value outside it is refused rather than stored: a grant no code resolves
    would read, in the owner's settings, as a power this deployment had conferred.
    """
    normalized: list[str] = []
    for value in values or []:
        cleaned = value.strip().lower() if isinstance(value, str) else ""
        if cleaned not in APP_SERVICE_GRANTS:
            raise _bad_request(
                AppServiceMessages.UNKNOWN_GRANT,
                f"{value!r} is not one of {sorted(APP_SERVICE_GRANTS)}",
            )
        if cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


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
    grants: Optional[Iterable[str]] = None,
    jwks: Optional[dict] = None,
    jwks_uri: Optional[str] = None,
    scope_ceiling: Optional[Iterable[str]] = None,
    mandatory: bool = False,
    enabled: bool = True,
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
    grant_list = normalize_grants(grants)
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
        grants=grant_list,
        jwks=key_set,
        jwks_uri=key_uri,
        scope_ceiling=ceiling,
        mandatory=mandatory,
        enabled=enabled,
    )
    session.add(row)
    await session.flush()
    await audit_service.record(
        session,
        event_type=AuditEventType.APP_SERVICE_CREATED,
        actor_user_id=actor_user_id,
        target_type="app_service_registration",
        target_id=row.id,
        detail=audit_service.changed_fields(
            {}, audit_service.snapshot(row, AUDITED_FIELDS)
        ),
    )
    await session.commit()
    await session.refresh(row)
    invalidate_registrations()
    return row


async def update_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    listing_uid: Optional[str] = None,
    base_url: Optional[str] = None,
    embed_origin: Optional[str] = None,
    allowed_origins: Optional[Iterable[str]] = None,
    grants: Optional[Iterable[str]] = None,
    jwks: Optional[dict] = None,
    jwks_uri: Optional[str] = None,
    scope_ceiling: Optional[Iterable[str]] = None,
    mandatory: Optional[bool] = None,
    enabled: Optional[bool] = None,
    actor_user_id: int | None = None,
) -> AppServiceRegistration:
    """Edit a registration.

    An empty ``embed_origin`` clears it, putting both surfaces back on
    ``base_url``; an empty ``jwks_uri`` clears it. A ``jwks_uri`` kept while
    ``base_url`` moves is checked against the new origin.
    """
    row = await get_registration(session, registration_id)
    before = audit_service.snapshot(row, AUDITED_FIELDS)
    # Whether the origin list is still just the app's own origin. An untouched
    # list follows the address it was derived from; one an operator typed is
    # theirs and is left exactly as typed.
    origins_were_default = list(row.allowed_origins or []) == [
        origin_of(browser_base(row))
    ]

    if listing_uid is not None:
        row.listing_uid = normalize_listing_uid(listing_uid)
    if base_url is not None:
        row.base_url = normalize_base_url(base_url)
    if embed_origin is not None:
        cleaned = embed_origin.strip()
        row.embed_origin = normalize_embed_origin(cleaned) if cleaned else None
    if allowed_origins is not None:
        row.allowed_origins = normalize_origins(
            allowed_origins, browser_base=browser_base(row)
        )
    elif origins_were_default:
        row.allowed_origins = normalize_origins(None, browser_base=browser_base(row))
    if grants is not None:
        row.grants = normalize_grants(grants)
    if jwks is not None:
        # Replaces rather than merges, and an empty object clears: a key set is
        # provisioned whole, so two entries mean a rotation is in flight and
        # one means it is over.
        row.jwks = normalize_jwks(jwks)
    if jwks_uri is not None:
        row.jwks_uri = normalize_jwks_uri(jwks_uri, base_url=row.base_url)
    elif row.jwks_uri is not None and base_url is not None:
        row.jwks_uri = normalize_jwks_uri(row.jwks_uri, base_url=row.base_url)
    if scope_ceiling is not None:
        # Replaces rather than merges; an empty list is a ceiling of nothing.
        row.scope_ceiling = normalize_scope_ceiling(scope_ceiling)
    if mandatory is not None:
        row.mandatory = mandatory
    if enabled is not None:
        row.enabled = enabled

    row.updated_at = _now()
    session.add(row)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, AUDITED_FIELDS)
    )
    if changed["changed"]:
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


async def delete_registration(
    session: AsyncSession, registration_id: int, *, actor_user_id: int | None = None
) -> None:
    row = await get_registration(session, registration_id)
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


async def reconcile_from_config(session: AsyncSession) -> ReconcileResult:
    """Bring the table in line with the mounted config file.

    Each entry is ``{public_id, listing_uid, base_url}`` and optionally
    ``embed_origin``, ``allowed_origins``, ``grants``, ``jwks``, ``jwks_uri``,
    ``scope_ceiling`` and ``mandatory``. Database-only: this upserts rows and
    stops.

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
    for entry in entries:
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
            grants = normalize_grants(entry.get("grants"))
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

        if public_id in seen:
            logger.warning(
                "app services: %r appears more than once in %s — later entry skipped",
                public_id,
                path,
            )
            skipped += 1
            continue
        seen.add(public_id)

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
                grants=grants,
                jwks=key_set,
                jwks_uri=key_uri,
                scope_ceiling=ceiling,
                mandatory=mandatory,
                enabled=True,
            )
            session.add(fresh)
            born.append(fresh)
            created += 1
            continue

        # The file is the declarative source for what the app IS and may do.
        # `enabled` is deliberately not reconciled: turning a registration off
        # is an operator action, and a restart must not reverse it.
        dirty = (
            listing_uid != row.listing_uid
            or base_url != row.base_url
            or embed != row.embed_origin
            or origins != list(row.allowed_origins or [])
            or grants != list(row.grants or [])
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
        row.grants = grants
        row.jwks = key_set
        row.jwks_uri = key_uri
        row.scope_ceiling = ceiling
        row.mandatory = mandatory
        row.updated_at = _now()
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
