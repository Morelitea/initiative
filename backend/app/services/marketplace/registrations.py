"""Managing the deployment's app service registrations.

Two ways a registration arrives, and they meet in the same upsert:

* **An operator adds one** through the ``apps.manage`` endpoints. That path runs
  the handshake (:mod:`app.services.marketplace.handshake`) so the row is born
  either verified or carrying the reason it is not.
* **The deployment declares them** in ``APP_SERVICES_CONFIG``, a file a chart
  mounts. That path is deliberately **offline**: reconciliation touches the
  database only, because an app container may well boot after Initiative does
  and a startup step must not depend on it. Rows land ``unverified`` and are
  confirmed by the operator's verify, or by a later sweep.

Two rules the reconciler keeps, both about not undoing a person:

* it never re-enables a registration an operator disabled — deactivating an app
  is the incident-response lever, so a restart must not quietly reverse it;
* changing the base URL or the secret clears the recorded verification, because
  a stored manifest hash describes the target it was fetched from and nothing
  else.

Everything here runs on the system engine: ``app_service_registrations`` has no
request-path write grant.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, status as http_status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import SALT_APP_SERVICE_SECRET, decrypt_field, encrypt_field
from app.core.messages import AppServiceMessages
from app.core.security import app_platform_signing_enabled
from app.models.platform.app_service_registration import (
    APP_SERVICE_GRANTS,
    AppServiceRegistration,
    AppServiceStatus,
)
from app.services.marketplace.handshake import HandshakeError, perform_handshake

logger = logging.getLogger(__name__)

__all__ = [
    "ReconcileResult",
    "check_signing_configured",
    "create_registration",
    "decrypt_secret",
    "delete_registration",
    "get_registration",
    "list_registrations",
    "normalize_base_url",
    "normalize_grants",
    "normalize_origin",
    "normalize_origins",
    "normalize_public_id",
    "reconcile_from_config",
    "update_registration",
    "verify_registration",
]

#: Characters a ``public_id`` may use: ``<publisher>.<slug>``, lowercase — the
#: same shape the catalog requires, checked as an explicit set so a stored id is
#: exactly what a URL and a JWT audience will carry.
_PUBLIC_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-_")
_MAX_PUBLIC_ID = 120
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


def normalize_base_url(value: str) -> str:
    """A base URL is a scheme, a host, an optional port, and an optional path
    prefix — nothing else. The egress policy (scheme vs address class) is
    applied when the connection is actually made, by ``safe_http``.
    """
    cleaned = (value or "").strip().rstrip("/")
    if not cleaned or len(cleaned) > _MAX_BASE_URL:
        raise _bad_request(
            AppServiceMessages.INVALID_BASE_URL,
            f"base_url must be 1..{_MAX_BASE_URL} characters",
        )
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise _bad_request(
            AppServiceMessages.INVALID_BASE_URL, "base_url must be http or https"
        )
    if not parsed.hostname:
        raise _bad_request(AppServiceMessages.INVALID_BASE_URL, "base_url needs a host")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise _bad_request(
            AppServiceMessages.INVALID_BASE_URL,
            "base_url carries no query, fragment, or credentials",
        )
    return cleaned


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
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def normalize_origins(values: Optional[Iterable[str]], *, base_url: str) -> list[str]:
    """Canonicalize the origin list, defaulting to the base URL's own origin."""
    items = [v for v in (values or []) if isinstance(v, str) and v.strip()]
    if not items:
        return [normalize_origin(base_url)]
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


def normalize_grants(values: Optional[Iterable[str]]) -> list[str]:
    """Check operator-conferred powers against the closed vocabulary.

    A value outside it is refused rather than stored: a grant no code resolves
    would read, in the admin UI, as a power this deployment had conferred.
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


# --- reads -------------------------------------------------------------------


async def list_registrations(
    session: AsyncSession,
) -> Sequence[AppServiceRegistration]:
    result = await session.exec(
        select(AppServiceRegistration).order_by(AppServiceRegistration.public_id.asc())
    )
    return result.all()


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


def decrypt_secret(row: AppServiceRegistration) -> str:
    """The registration's shared secret, or a refusal when it has none."""
    if not row.secret_encrypted:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=AppServiceMessages.SECRET_REQUIRED,
        )
    return decrypt_field(row.secret_encrypted, SALT_APP_SERVICE_SECRET)


# --- writes ------------------------------------------------------------------


def _clear_verification(row: AppServiceRegistration) -> None:
    """Forget what an earlier handshake established. Called whenever the target
    or the secret changes — a manifest hash describes one destination."""
    row.status = AppServiceStatus.UNVERIFIED
    row.manifest_hash = None
    row.protocol_version = None
    row.last_verified_at = None


async def create_registration(
    session: AsyncSession,
    *,
    base_url: str,
    secret: str,
    public_id: Optional[str] = None,
    allowed_origins: Optional[Iterable[str]] = None,
    grants: Optional[Iterable[str]] = None,
    mandatory: bool = False,
    enabled: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AppServiceRegistration:
    """Wire an app service up, verifying it on the way in.

    The handshake decides what the row knows about itself. When it succeeds the
    manifest supplies ``public_id`` and the catalog uid; when it fails, an
    operator who named the app anyway still gets a row — carrying the failure —
    so a service that has not booted yet can be registered ahead of time and
    verified once it answers.
    """
    check_signing_configured()
    base_url = normalize_base_url(base_url)
    origins = normalize_origins(allowed_origins, base_url=base_url)
    grant_list = normalize_grants(grants)
    declared_id = normalize_public_id(public_id) if public_id else None
    if not secret or not secret.strip():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=AppServiceMessages.SECRET_REQUIRED,
        )

    listing_uid: Optional[str] = None
    manifest_hash: Optional[str] = None
    protocol_version: Optional[int] = None
    verified_at: Optional[datetime] = None
    row_status = AppServiceStatus.OK
    resolved_id = declared_id

    try:
        result = await perform_handshake(
            base_url=base_url, secret=secret, transport=transport
        )
    except HandshakeError as exc:
        if declared_id is None:
            # Nothing names the row: without a manifest and without an operator
            # saying which app this is, there is no registration to store.
            raise HTTPException(
                status_code=http_status.HTTP_502_BAD_GATEWAY, detail=exc.code
            ) from exc
        row_status = exc.status
    else:
        # Normalized before it is compared or stored: how an app spells its own
        # id in its manifest is its business, but one canonical form is what
        # every later lookup and audience is built from.
        result_id = normalize_public_id(result.public_id)
        if declared_id is not None and declared_id != result_id:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=AppServiceMessages.PUBLIC_ID_MISMATCH,
            )
        resolved_id = result_id
        listing_uid = result.listing_uid
        manifest_hash = result.manifest_hash
        protocol_version = result.protocol_version
        verified_at = _now()

    if resolved_id is None:
        # Unreachable: the failure branch above returns when nothing names the
        # row, and the success branch takes the name from the manifest.
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=AppServiceMessages.INVALID_PUBLIC_ID,
        )
    if await _by_public_id(session, resolved_id) is not None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=AppServiceMessages.DUPLICATE_PUBLIC_ID,
        )

    row = AppServiceRegistration(
        public_id=resolved_id,
        listing_uid=listing_uid,
        base_url=base_url,
        allowed_origins=origins,
        secret_encrypted=encrypt_field(secret, SALT_APP_SERVICE_SECRET),
        manifest_hash=manifest_hash,
        protocol_version=protocol_version,
        grants=grant_list,
        mandatory=mandatory,
        enabled=enabled,
        status=row_status,
        last_verified_at=verified_at,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def update_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    base_url: Optional[str] = None,
    secret: Optional[str] = None,
    allowed_origins: Optional[Iterable[str]] = None,
    grants: Optional[Iterable[str]] = None,
    mandatory: Optional[bool] = None,
    enabled: Optional[bool] = None,
) -> AppServiceRegistration:
    """Edit a registration. Rotating the secret or repointing the base URL
    discards the recorded verification — re-verify after either."""
    row = await get_registration(session, registration_id)
    retarget = False

    if base_url is not None:
        new_url = normalize_base_url(base_url)
        retarget = retarget or new_url != row.base_url
        row.base_url = new_url
    if secret is not None:
        if not secret.strip():
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=AppServiceMessages.SECRET_REQUIRED,
            )
        row.secret_encrypted = encrypt_field(secret, SALT_APP_SERVICE_SECRET)
        retarget = True
    if allowed_origins is not None:
        row.allowed_origins = normalize_origins(allowed_origins, base_url=row.base_url)
    if grants is not None:
        row.grants = normalize_grants(grants)
    if mandatory is not None:
        row.mandatory = mandatory
    if enabled is not None:
        row.enabled = enabled

    if retarget:
        _clear_verification(row)
    row.updated_at = _now()
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def delete_registration(session: AsyncSession, registration_id: int) -> None:
    row = await get_registration(session, registration_id)
    await session.delete(row)
    await session.commit()


async def verify_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    accept_manifest_change: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AppServiceRegistration:
    """Re-run the handshake and record what it found.

    The outcome is persisted before any refusal is raised, so the row always
    reflects the most recent attempt — an operator reading the list sees the
    same answer the request returned.
    """
    check_signing_configured()
    row = await get_registration(session, registration_id)
    secret = decrypt_secret(row)

    async def _persist(**fields: Any) -> None:
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = _now()
        session.add(row)
        await session.commit()
        await session.refresh(row)

    try:
        result = await perform_handshake(
            base_url=row.base_url, secret=secret, transport=transport
        )
    except HandshakeError as exc:
        await _persist(status=exc.status)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY, detail=exc.code
        ) from exc

    if result.public_id != row.public_id:
        await _persist(status=AppServiceStatus.MANIFEST_MISMATCH)
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=AppServiceMessages.PUBLIC_ID_MISMATCH,
        )

    changed = (
        row.manifest_hash is not None and row.manifest_hash != result.manifest_hash
    )
    if changed and not accept_manifest_change:
        await _persist(status=AppServiceStatus.MANIFEST_MISMATCH)
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=AppServiceMessages.MANIFEST_CHANGED,
        )

    await _persist(
        status=AppServiceStatus.OK,
        listing_uid=result.listing_uid,
        manifest_hash=result.manifest_hash,
        protocol_version=result.protocol_version,
        last_verified_at=_now(),
    )
    return row


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

    Offline by design: this upserts rows and stops. Verification is a separate,
    network-bound step so a boot never waits on someone else's container.

    A malformed file, an unreadable path, or an entry naming an environment
    variable that is not set costs that entry (or that file) and nothing else —
    the caller keeps booting.
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
    # A public_id already handled in this pass. The row for it is pending rather
    # than flushed, so a second entry naming it would look absent, insert a
    # duplicate, and fail the unique constraint at the shared commit — taking
    # every other registration in the file down with it.
    seen: set[str] = set()
    for entry in entries:
        try:
            public_id = normalize_public_id(str(entry.get("public_id", "")))
            base_url = normalize_base_url(str(entry.get("base_url", "")))
            origins = normalize_origins(entry.get("allowed_origins"), base_url=base_url)
            grants = normalize_grants(entry.get("grants"))
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

        secret_env = entry.get("secret_env")
        secret = os.environ.get(secret_env) if isinstance(secret_env, str) else None
        if not secret:
            logger.warning(
                "app services: %s names secret_env %r, which is not set — skipped",
                public_id,
                secret_env,
            )
            skipped += 1
            continue

        mandatory = bool(entry.get("mandatory", False))
        row = await _by_public_id(session, public_id)
        if row is None:
            session.add(
                AppServiceRegistration(
                    public_id=public_id,
                    base_url=base_url,
                    allowed_origins=origins,
                    secret_encrypted=encrypt_field(secret, SALT_APP_SERVICE_SECRET),
                    grants=grants,
                    mandatory=mandatory,
                    enabled=True,
                    status=AppServiceStatus.UNVERIFIED,
                )
            )
            created += 1
            continue

        # The file is the declarative source for what the app IS and may do.
        # `enabled` is deliberately not reconciled: turning a registration off
        # is an operator action, and a restart must not reverse it.
        current_secret = (
            decrypt_field(row.secret_encrypted, SALT_APP_SERVICE_SECRET)
            if row.secret_encrypted
            else None
        )
        retarget = base_url != row.base_url or secret != current_secret
        dirty = (
            retarget
            or origins != list(row.allowed_origins or [])
            or grants != list(row.grants or [])
            or mandatory != row.mandatory
        )
        if not dirty:
            unchanged += 1
            continue

        row.base_url = base_url
        row.allowed_origins = origins
        row.grants = grants
        row.mandatory = mandatory
        if retarget:
            row.secret_encrypted = encrypt_field(secret, SALT_APP_SERVICE_SECRET)
            _clear_verification(row)
        row.updated_at = _now()
        session.add(row)
        updated += 1

    await session.commit()
    return ReconcileResult(
        created=created, updated=updated, unchanged=unchanged, skipped=skipped
    )
